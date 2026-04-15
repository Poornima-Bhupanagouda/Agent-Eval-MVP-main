"""
Tracing Module for Lilly Agent Eval.

Provides:
  - LangSmith configuration and connection management
  - OpenTelemetry configuration detection
  - AgentTrace: a normalized, framework-agnostic trace format
  - Converters: LangSmith raw traces → AgentTrace, local traces → AgentTrace
  - TracingContext: context manager for wrapping agent execution with LangSmith

Dual-mode tracing:
  - LangSmith: sends traces to LangSmith cloud (LangChain ecosystem)
  - OpenTelemetry: sends spans to any OTel collector (Jaeger/Grafana/Datadog)
  - Both can run simultaneously or independently

This module bridges execution recording with our evaluator's
AgentTrace format, enabling process-level metrics (tool_usage_correctness,
tool_order_correctness, failure_recovery, step_count_limit).
"""

import os
import time
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# 1. AgentTrace — Framework-agnostic trace model
# ─────────────────────────────────────────────

@dataclass
class TraceStep:
    """One step in an agent's execution path."""
    node_name: str
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[Any] = None
    duration_ms: int = 0
    timestamp: float = 0.0
    status: str = "ok"  # "ok" | "error"
    error: Optional[str] = None


@dataclass
class AgentTrace:
    """
    Normalized trace of an agent execution.

    This is the common format that the evaluator consumes.
    It is populated from LangSmith traces OR from the existing
    TracedGraph trace entries.
    """
    agent_name: str = ""
    run_id: str = ""
    steps: List[TraceStep] = field(default_factory=list)
    total_duration_ms: int = 0
    final_output: str = ""
    reasoning_steps: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    messages: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def node_names(self) -> List[str]:
        return [s.node_name for s in self.steps]

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def has_errors(self) -> bool:
        return any(s.status == "error" for s in self.steps)

    @property
    def error_nodes(self) -> List[str]:
        return [s.node_name for s in self.steps if s.status == "error"]

    @property
    def success_rate(self) -> float:
        if not self.steps:
            return 0.0
        ok = sum(1 for s in self.steps if s.status == "ok")
        return ok / len(self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "run_id": self.run_id,
            "steps": [
                {
                    "node_name": s.node_name,
                    "tool_name": s.tool_name,
                    "tool_input": s.tool_input,
                    "tool_output": s.tool_output,
                    "duration_ms": s.duration_ms,
                    "timestamp": s.timestamp,
                    "status": s.status,
                    "error": s.error,
                }
                for s in self.steps
            ],
            "total_duration_ms": self.total_duration_ms,
            "final_output": self.final_output,
            "reasoning_steps": self.reasoning_steps,
            "tool_calls": self.tool_calls,
            "messages": self.messages,
            "metadata": self.metadata,
        }


# ─────────────────────────────────────────────
# 2. LangSmith configuration helper
# ─────────────────────────────────────────────

def is_langsmith_enabled() -> bool:
    """Check if LangSmith tracing is configured and enabled."""
    tracing_flag = os.getenv("LANGCHAIN_TRACING_V2", "false").lower()
    api_key = os.getenv("LANGCHAIN_API_KEY", "")
    return tracing_flag == "true" and bool(api_key) and not api_key.startswith("lsv2_pt_REPLACE")


def get_langsmith_client():
    """Get a LangSmith client instance, or None if not configured."""
    if not is_langsmith_enabled():
        logger.info("LangSmith tracing is not enabled (set LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY)")
        return None
    try:
        from langsmith import Client
        return Client()
    except Exception as e:
        logger.warning(f"Failed to create LangSmith client: {e}")
        return None


# ─────────────────────────────────────────────
# 2b. OpenTelemetry configuration helper
# ─────────────────────────────────────────────

def is_otel_enabled() -> bool:
    """Check if OpenTelemetry tracing is configured and enabled."""
    try:
        from agent_eval.core.otel_tracing import is_otel_enabled as _otel_check
        return _otel_check()
    except ImportError:
        return False


def get_tracing_status() -> dict:
    """
    Return current tracing configuration status.

    Returns dict with:
        langsmith_enabled: bool
        otel_enabled: bool
        mode: str ("none" | "langsmith" | "otel" | "both")
    """
    ls = is_langsmith_enabled()
    otel = is_otel_enabled()
    if ls and otel:
        mode = "both"
    elif ls:
        mode = "langsmith"
    elif otel:
        mode = "otel"
    else:
        mode = "none"
    return {"langsmith_enabled": ls, "otel_enabled": otel, "mode": mode}


# ─────────────────────────────────────────────
# 3. Converter: TracedGraph trace → AgentTrace
# ─────────────────────────────────────────────

def convert_trace_to_agent_trace(
    trace_entries: List[Dict[str, Any]],
    agent_name: str = "",
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    output: str = "",
    run_id: str = "",
) -> AgentTrace:
    """
    Convert the existing TracedGraph trace list into our AgentTrace format.

    This works with the trace format already emitted by TracedGraph:
        [{"node": "retrieve", "duration_ms": 45, "result": "ok", "error": None}, ...]

    Args:
        trace_entries: List of trace dicts from TracedGraph state["trace"]
        agent_name: Name of the agent
        tool_calls: List of tool calls from the agent response
        output: Final output string
        run_id: Optional run ID (from LangSmith or generated)

    Returns:
        AgentTrace with normalized steps
    """
    steps = []
    reasoning = []
    total_ms = 0

    for entry in trace_entries:
        node = entry.get("node", "unknown")
        duration = entry.get("duration_ms", 0)
        result = entry.get("result", "ok")
        error = entry.get("error")

        step = TraceStep(
            node_name=node,
            duration_ms=duration,
            timestamp=time.time(),
            status="error" if error else "ok",
            error=error,
        )
        steps.append(step)
        total_ms += duration

        # Build reasoning narrative
        if error:
            reasoning.append(f"[{node}] FAILED: {error} ({duration}ms)")
        else:
            reasoning.append(f"[{node}] completed ({duration}ms)")

    # Normalize tool_calls
    normalized_tools = []
    if tool_calls:
        for tc in tool_calls:
            normalized_tools.append({
                "name": tc.get("name", tc.get("tool", "unknown")),
                "input": tc.get("args", tc.get("tool_input", tc.get("input", {}))),
                "output": tc.get("output", tc.get("result", None)),
            })
            # Also attach tool info to the matching step
            for step in steps:
                tool_name = tc.get("name", tc.get("tool", ""))
                if tool_name and tool_name.lower() in step.node_name.lower():
                    step.tool_name = tool_name
                    step.tool_input = tc.get("args", tc.get("tool_input", {}))
                    step.tool_output = tc.get("output", tc.get("result", None))

    return AgentTrace(
        agent_name=agent_name,
        run_id=run_id or f"local-{int(time.time()*1000)}",
        steps=steps,
        total_duration_ms=total_ms,
        final_output=output,
        reasoning_steps=reasoning,
        tool_calls=normalized_tools,
        metadata={"source": "traced_graph", "step_count": len(steps)},
    )


# ─────────────────────────────────────────────
# 4. Converter: LangSmith run → AgentTrace
# ─────────────────────────────────────────────

def convert_langsmith_run_to_agent_trace(run) -> AgentTrace:
    """
    Convert a LangSmith Run object into our AgentTrace format.

    LangSmith runs contain:
      - run.name: the chain/node name
      - run.child_runs: nested sub-runs (nodes, tools, LLM calls)
      - run.inputs / run.outputs
      - run.start_time / run.end_time
      - run.error

    Args:
        run: A LangSmith Run object (from client.read_run() or list_runs())

    Returns:
        AgentTrace with all steps extracted from child runs
    """
    steps = []
    tool_calls = []
    reasoning = []
    messages = []

    def _process_run(r, depth=0):
        """Recursively process a run and its children."""
        name = getattr(r, "name", "unknown")
        run_type = getattr(r, "run_type", "chain")
        start = getattr(r, "start_time", None)
        end = getattr(r, "end_time", None)
        error = getattr(r, "error", None)
        inputs = getattr(r, "inputs", {}) or {}
        outputs = getattr(r, "outputs", {}) or {}

        duration_ms = 0
        if start and end:
            duration_ms = int((end - start).total_seconds() * 1000)

        timestamp = start.timestamp() if start else time.time()

        step = TraceStep(
            node_name=name,
            duration_ms=duration_ms,
            timestamp=timestamp,
            status="error" if error else "ok",
            error=error,
        )

        # Capture tool-specific info
        if run_type == "tool":
            step.tool_name = name
            step.tool_input = inputs
            step.tool_output = outputs
            tool_calls.append({
                "name": name,
                "input": inputs,
                "output": outputs,
            })

        # Capture LLM messages
        if run_type == "llm":
            if "messages" in inputs:
                for msg in inputs["messages"]:
                    if isinstance(msg, list):
                        for m in msg:
                            messages.append(_extract_message(m))
                    else:
                        messages.append(_extract_message(msg))

        steps.append(step)
        prefix = "  " * depth
        if error:
            reasoning.append(f"{prefix}[{name}] FAILED: {error} ({duration_ms}ms)")
        else:
            reasoning.append(f"{prefix}[{name}] completed ({duration_ms}ms)")

        # Process child runs
        children = getattr(r, "child_runs", None) or []
        for child in children:
            _process_run(child, depth + 1)

    _process_run(run)

    # Calculate total from root run
    root_start = getattr(run, "start_time", None)
    root_end = getattr(run, "end_time", None)
    total_ms = 0
    if root_start and root_end:
        total_ms = int((root_end - root_start).total_seconds() * 1000)

    # Final output
    outputs = getattr(run, "outputs", {}) or {}
    final_output = ""
    if isinstance(outputs, dict):
        final_output = outputs.get("output", outputs.get("response", str(outputs)))

    return AgentTrace(
        agent_name=getattr(run, "name", ""),
        run_id=str(getattr(run, "id", "")),
        steps=steps,
        total_duration_ms=total_ms,
        final_output=str(final_output),
        reasoning_steps=reasoning,
        tool_calls=tool_calls,
        messages=messages,
        metadata={
            "source": "langsmith",
            "step_count": len(steps),
            "run_type": getattr(run, "run_type", "unknown"),
        },
    )


def _extract_message(msg) -> Dict[str, Any]:
    """Extract role/content from various LangChain message formats."""
    if isinstance(msg, dict):
        return {
            "role": msg.get("role", msg.get("type", "unknown")),
            "content": msg.get("content", str(msg)),
        }
    # LangChain message objects
    role = getattr(msg, "type", getattr(msg, "role", "unknown"))
    content = getattr(msg, "content", str(msg))
    return {"role": role, "content": content}


# ─────────────────────────────────────────────
# 5. Fetch LangSmith traces for a run
# ─────────────────────────────────────────────

def fetch_langsmith_trace(run_id: str) -> Optional[AgentTrace]:
    """
    Fetch a specific run from LangSmith and convert to AgentTrace.

    Args:
        run_id: The LangSmith run ID

    Returns:
        AgentTrace or None if not available
    """
    client = get_langsmith_client()
    if not client:
        return None

    try:
        run = client.read_run(run_id)
        return convert_langsmith_run_to_agent_trace(run)
    except Exception as e:
        logger.warning(f"Failed to fetch LangSmith trace {run_id}: {e}")
        return None


def list_recent_traces(project_name: Optional[str] = None, limit: int = 10) -> List[AgentTrace]:
    """
    List recent traces from LangSmith project.

    Args:
        project_name: LangSmith project (defaults to LANGCHAIN_PROJECT env var)
        limit: Max traces to return

    Returns:
        List of AgentTrace objects
    """
    client = get_langsmith_client()
    if not client:
        return []

    project = project_name or os.getenv("LANGCHAIN_PROJECT", "lilly-agent-eval")
    traces = []

    try:
        runs = client.list_runs(project_name=project, limit=limit, is_root=True)
        for run in runs:
            traces.append(convert_langsmith_run_to_agent_trace(run))
    except Exception as e:
        logger.warning(f"Failed to list LangSmith traces: {e}")

    return traces
