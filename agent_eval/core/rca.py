"""
Root Cause Analysis (RCA) Agent — STEP 5 of AgentEval.

A rule-based decision tree that diagnoses WHY an agent failed,
not just WHETHER it failed.

Reads evaluation metrics + execution traces and outputs structured
root-cause diagnoses with evidence and confidence scores.

Architecture:
    Metric Evaluation (STEP 4)
         ↓
    Root Cause Analysis (THIS)  ← rule-based decision tree
         ↓
    Optimization / Deploy / Block (STEP 6/7)

RCA Cases (from AgentEval design):
    1. Retrieval Failure  — faithfulness ↓ AND context_precision ↓
    2. Prompt Failure     — faithfulness ↓ AND context_precision OK
    3. Planning Failure   — tool metrics ↓ OR agent_reasoning ↓
    4. Performance Failure — latency ↑ AND quality OK
    5. Memory Failure     — context_retention ↓ OR memory_retention ↓
    6. Safety Failure     — toxicity ↓ OR bias ↓
    7. Robustness Failure — failure_recovery ↓ OR step_count ↓
"""

import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class RCADiagnosis:
    """A single root-cause diagnosis."""
    root_cause: str          # e.g. "retrieval_failure"
    category: str            # e.g. "Retrieval", "Prompt", "Planning"
    confidence: float        # 0.0 - 1.0
    evidence: List[str]      # List of evidence statements
    recommendation: str      # What to fix
    failed_metrics: List[str]  # Which metrics triggered this

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RCAResult:
    """Complete RCA output for a test result."""
    has_failures: bool
    diagnoses: List[RCADiagnosis] = field(default_factory=list)
    summary: str = ""
    metrics_analyzed: int = 0
    trace_available: bool = False

    def to_dict(self) -> dict:
        return {
            "has_failures": self.has_failures,
            "diagnoses": [d.to_dict() for d in self.diagnoses],
            "summary": self.summary,
            "metrics_analyzed": self.metrics_analyzed,
            "trace_available": self.trace_available,
        }


# ---------------------------------------------------------------------------
# RCA Agent — rule-based decision tree
# ---------------------------------------------------------------------------

class RCAAgent:
    """
    Root Cause Analysis agent using a rule-based decision tree.

    Takes evaluation scores + trace data → diagnoses WHY quality is low.

    Pipeline:
        collect_signals → classify_failures → diagnose → summarize
    """

    # Thresholds for "low" scores (below these trigger investigation)
    LOW_THRESHOLD = 70.0
    MEDIUM_THRESHOLD = 80.0

    def analyze(
        self,
        evaluations: List[Dict],
        trace: Optional[List[Dict]] = None,
        tool_calls: Optional[List[Dict]] = None,
        latency_ms: int = 0,
        expected_behavior: Optional[Dict] = None,
    ) -> RCAResult:
        """
        Run the full RCA pipeline.

        Args:
            evaluations: List of {"metric", "score", "passed", "reason"} dicts
            trace: Agent execution trace
            tool_calls: Agent tool calls
            latency_ms: Total response latency
            expected_behavior: Expected tools/steps/recovery from test case

        Returns:
            RCAResult with diagnoses
        """
        # Build internal state
        state = {
            "evaluations": evaluations,
            "trace": trace or [],
            "tool_calls": tool_calls or [],
            "latency_ms": latency_ms,
            "expected_behavior": expected_behavior or {},
        }

        # Step 1: Collect signals (extract metric scores into a lookup)
        signals = self._collect_signals(state)

        # Step 2: Check if there are any failures worth diagnosing
        failed_metrics = [m for m, s in signals["scores"].items() if s < self.LOW_THRESHOLD]

        if not failed_metrics:
            return RCAResult(
                has_failures=False,
                summary="All metrics passed — no root cause analysis needed.",
                metrics_analyzed=len(signals["scores"]),
                trace_available=bool(trace),
            )

        # Step 3: Run decision tree
        diagnoses = []
        diagnoses += self._check_retrieval_failure(signals)
        diagnoses += self._check_prompt_failure(signals)
        diagnoses += self._check_planning_failure(signals)
        diagnoses += self._check_performance_failure(signals)
        diagnoses += self._check_memory_failure(signals)
        diagnoses += self._check_safety_failure(signals)
        diagnoses += self._check_robustness_failure(signals)

        # Step 4: If we found failed metrics but no specific diagnosis matched,
        # produce a generic diagnosis
        diagnosed_metrics = set()
        for d in diagnoses:
            diagnosed_metrics.update(d.failed_metrics)

        undiagnosed = [m for m in failed_metrics if m not in diagnosed_metrics]
        if undiagnosed:
            diagnoses.append(RCADiagnosis(
                root_cause="unclassified_failure",
                category="General",
                confidence=0.5,
                evidence=[f"{m}: {signals['scores'].get(m, 0):.0f}%" for m in undiagnosed],
                recommendation="Review the failing metrics individually. The failure pattern doesn't match a known root cause.",
                failed_metrics=undiagnosed,
            ))

        # Step 5: Sort by confidence (highest first)
        diagnoses.sort(key=lambda d: d.confidence, reverse=True)

        # Step 6: Build summary
        summary = self._build_summary(diagnoses, signals)

        return RCAResult(
            has_failures=True,
            diagnoses=diagnoses,
            summary=summary,
            metrics_analyzed=len(signals["scores"]),
            trace_available=bool(trace),
        )

    # ------------------------------------------------------------------
    # Step 1: Signal collection
    # ------------------------------------------------------------------

    def _collect_signals(self, state: Dict) -> Dict:
        """Extract all signals from evaluation state into a structured lookup."""
        scores = {}
        reasons = {}
        for ev in state["evaluations"]:
            metric = ev.get("metric", "")
            scores[metric] = ev.get("score", 0)
            reasons[metric] = ev.get("reason", "")

        # Trace signals
        trace = state.get("trace", [])
        trace_nodes = [t.get("node", "") for t in trace]
        trace_errors = [t for t in trace if t.get("error") or t.get("result", "ok") != "ok"]
        total_trace_ms = sum(t.get("duration_ms", 0) for t in trace)

        # Tool signals
        tool_calls = state.get("tool_calls", [])
        tool_names = [tc.get("name", tc.get("tool", "")) for tc in tool_calls]

        return {
            "scores": scores,
            "reasons": reasons,
            "trace_nodes": trace_nodes,
            "trace_errors": trace_errors,
            "trace_node_count": len(trace_nodes),
            "total_trace_ms": total_trace_ms,
            "tool_names": tool_names,
            "tool_count": len(tool_calls),
            "latency_ms": state.get("latency_ms", 0),
            "expected_behavior": state.get("expected_behavior", {}),
        }

    # ------------------------------------------------------------------
    # Decision tree cases
    # ------------------------------------------------------------------

    def _check_retrieval_failure(self, signals: Dict) -> List[RCADiagnosis]:
        """Case 1: Retriever failure.
        IF faithfulness ↓ AND context_precision ↓ → retrieval problem
        """
        scores = signals["scores"]
        faithfulness = scores.get("faithfulness", None)
        ctx_relevancy = scores.get("contextual_relevancy", None)
        hallucination = scores.get("hallucination", None)
        precision = scores.get("precision_at_k", None)
        recall = scores.get("recall_at_k", None)

        if faithfulness is None and ctx_relevancy is None:
            return []  # No retrieval metrics to analyze

        evidence = []
        failed = []
        confidence = 0.0

        # Strong signal: both faithfulness and context relevancy are low
        if faithfulness is not None and faithfulness < self.LOW_THRESHOLD:
            evidence.append(f"Faithfulness is low ({faithfulness:.0f}%) — response not grounded in context")
            failed.append("faithfulness")
            confidence += 0.3

        if ctx_relevancy is not None and ctx_relevancy < self.LOW_THRESHOLD:
            evidence.append(f"Contextual relevancy is low ({ctx_relevancy:.0f}%) — retrieved context not relevant to query")
            failed.append("contextual_relevancy")
            confidence += 0.3

        if precision is not None and precision < self.LOW_THRESHOLD:
            evidence.append(f"Precision@K is low ({precision:.0f}%) — too many irrelevant chunks retrieved")
            failed.append("precision_at_k")
            confidence += 0.15

        if recall is not None and recall < self.LOW_THRESHOLD:
            evidence.append(f"Recall@K is low ({recall:.0f}%) — relevant information not retrieved")
            failed.append("recall_at_k")
            confidence += 0.15

        if hallucination is not None and hallucination < self.LOW_THRESHOLD:
            evidence.append(f"Hallucination score is low ({hallucination:.0f}%) — model making up facts")
            failed.append("hallucination")
            confidence += 0.1

        if not failed:
            return []

        confidence = min(confidence, 1.0)

        return [RCADiagnosis(
            root_cause="retrieval_failure",
            category="Retrieval",
            confidence=round(confidence, 2),
            evidence=evidence,
            recommendation="Check retrieval pipeline: increase top_k, adjust chunk size, verify embedding model matches query domain, or add re-ranking.",
            failed_metrics=failed,
        )]

    def _check_prompt_failure(self, signals: Dict) -> List[RCADiagnosis]:
        """Case 2: Prompt failure.
        IF faithfulness ↓ AND context_precision OK → prompt problem
        """
        scores = signals["scores"]
        faithfulness = scores.get("faithfulness", None)
        ctx_relevancy = scores.get("contextual_relevancy", None)
        answer_rel = scores.get("answer_relevancy", None)

        if faithfulness is None:
            return []

        # Key signal: faithfulness low but context was actually relevant
        ctx_ok = ctx_relevancy is None or ctx_relevancy >= self.LOW_THRESHOLD
        faith_low = faithfulness < self.LOW_THRESHOLD

        if not (faith_low and ctx_ok):
            return []

        evidence = [
            f"Faithfulness is low ({faithfulness:.0f}%) but context retrieval is fine",
            "This means the model received good context but didn't use it correctly",
        ]
        failed = ["faithfulness"]
        confidence = 0.7

        if answer_rel is not None and answer_rel < self.LOW_THRESHOLD:
            evidence.append(f"Answer relevancy also low ({answer_rel:.0f}%) — model may be ignoring instructions")
            failed.append("answer_relevancy")
            confidence = 0.85

        return [RCADiagnosis(
            root_cause="prompt_failure",
            category="Prompt",
            confidence=round(confidence, 2),
            evidence=evidence,
            recommendation="Improve the system prompt: enforce citation of sources, add explicit grounding instructions, or use 'answer only from the provided context' constraint.",
            failed_metrics=failed,
        )]

    def _check_planning_failure(self, signals: Dict) -> List[RCADiagnosis]:
        """Case 3: Agent planning/tool failure.
        IF tool metrics ↓ OR agent_reasoning ↓ → planning error
        """
        scores = signals["scores"]
        evidence = []
        failed = []
        confidence = 0.0

        tool_usage = scores.get("tool_usage_correctness", None)
        tool_order = scores.get("tool_order_correctness", None)
        tool_correct = scores.get("tool_correctness", None)
        reasoning = scores.get("agent_reasoning", None)

        if tool_usage is not None and tool_usage < self.LOW_THRESHOLD:
            evidence.append(f"Tool usage correctness is low ({tool_usage:.0f}%) — wrong tools were selected")
            failed.append("tool_usage_correctness")
            confidence += 0.3

        if tool_order is not None and tool_order < self.LOW_THRESHOLD:
            evidence.append(f"Tool order is wrong ({tool_order:.0f}%) — tools called in incorrect sequence")
            failed.append("tool_order_correctness")
            confidence += 0.25

        if tool_correct is not None and tool_correct < self.LOW_THRESHOLD:
            evidence.append(f"Tool correctness is low ({tool_correct:.0f}%) — expected tools not invoked")
            failed.append("tool_correctness")
            confidence += 0.25

        if reasoning is not None and reasoning < self.LOW_THRESHOLD:
            evidence.append(f"Agent reasoning is weak ({reasoning:.0f}%) — no structured plan→execute→synthesize pattern")
            failed.append("agent_reasoning")
            confidence += 0.2

        # Trace evidence: wrong node flow
        if signals["trace_errors"]:
            error_nodes = [e.get("node", "?") for e in signals["trace_errors"]]
            evidence.append(f"Trace shows errors at nodes: {', '.join(error_nodes)}")
            confidence += 0.1

        if not failed:
            return []

        confidence = min(confidence, 1.0)

        # Determine specific sub-type
        if tool_usage is not None and tool_usage < self.LOW_THRESHOLD:
            root_cause = "wrong_tool_selected"
            recommendation = "Review agent's tool selection logic. The planner chose the wrong tool for this task. Check routing rules or add tool descriptions."
        elif tool_order is not None and tool_order < self.LOW_THRESHOLD:
            root_cause = "wrong_tool_order"
            recommendation = "Review agent's planning sequence. Tools were called in the wrong order. Check if the planner has dependency awareness."
        else:
            root_cause = "planning_failure"
            recommendation = "Review agent's reasoning pipeline. The plan→execute→synthesize pattern is broken or missing."

        return [RCADiagnosis(
            root_cause=root_cause,
            category="Planning",
            confidence=round(confidence, 2),
            evidence=evidence,
            recommendation=recommendation,
            failed_metrics=failed,
        )]

    def _check_performance_failure(self, signals: Dict) -> List[RCADiagnosis]:
        """Case 4: Performance failure.
        IF latency high AND quality OK → inefficiency
        """
        scores = signals["scores"]
        latency = signals["latency_ms"]
        step_latency = scores.get("step_latency", None)
        step_count = scores.get("step_count_limit", None)

        # Check if quality is actually OK (most metrics pass)
        quality_scores = [s for m, s in scores.items()
                         if m in ("answer_relevancy", "faithfulness", "task_completion", "similarity")]
        quality_ok = all(s >= self.LOW_THRESHOLD for s in quality_scores) if quality_scores else True

        evidence = []
        failed = []
        confidence = 0.0

        if step_latency is not None and step_latency < self.LOW_THRESHOLD:
            evidence.append(f"Step latency score is low ({step_latency:.0f}%) — one step dominates execution time")
            failed.append("step_latency")
            confidence += 0.3

        if step_count is not None and step_count < self.LOW_THRESHOLD:
            evidence.append(f"Step count score is low ({step_count:.0f}%) — too many execution steps")
            failed.append("step_count_limit")
            confidence += 0.3

        if latency > 10000:  # >10 seconds is slow
            evidence.append(f"Total latency is {latency}ms ({latency/1000:.1f}s) — slow response")
            confidence += 0.2
        elif latency > 5000:
            evidence.append(f"Total latency is {latency}ms — moderately slow")
            confidence += 0.1

        if not failed and latency <= 5000:
            return []

        if not failed:
            return []

        confidence = min(confidence, 1.0)

        if quality_ok:
            recommendation = "The agent produces good results but is slow. Reduce chunk sizes, limit reasoning loops, cache repeated lookups, or parallelize independent tool calls."
        else:
            recommendation = "The agent is both slow AND producing poor results. Focus on fixing quality first (see other diagnoses), then optimize performance."

        return [RCADiagnosis(
            root_cause="performance_failure",
            category="Performance",
            confidence=round(confidence, 2),
            evidence=evidence,
            recommendation=recommendation,
            failed_metrics=failed,
        )]

    def _check_memory_failure(self, signals: Dict) -> List[RCADiagnosis]:
        """Case 5: Memory failure.
        IF context_retention ↓ OR memory_retention ↓ → memory problem
        """
        scores = signals["scores"]
        ctx_retention = scores.get("context_retention", None)
        mem_retention = scores.get("memory_retention", None)
        coherence = scores.get("coherence", None)

        evidence = []
        failed = []
        confidence = 0.0

        if ctx_retention is not None and ctx_retention < self.LOW_THRESHOLD:
            evidence.append(f"Context retention is low ({ctx_retention:.0f}%) — agent forgets earlier conversation turns")
            failed.append("context_retention")
            confidence += 0.35

        if mem_retention is not None and mem_retention < self.LOW_THRESHOLD:
            evidence.append(f"Memory retention is low ({mem_retention:.0f}%) — agent doesn't use remembered facts (name, preferences)")
            failed.append("memory_retention")
            confidence += 0.35

        if coherence is not None and coherence < self.LOW_THRESHOLD:
            evidence.append(f"Coherence is low ({coherence:.0f}%) — responses don't follow logically from conversation")
            failed.append("coherence")
            confidence += 0.2

        if not failed:
            return []

        confidence = min(confidence, 1.0)

        return [RCADiagnosis(
            root_cause="memory_failure",
            category="Memory",
            confidence=round(confidence, 2),
            evidence=evidence,
            recommendation="Check conversation memory: ensure session_id is passed, verify conversation_history is seeded, or increase context window size.",
            failed_metrics=failed,
        )]

    def _check_safety_failure(self, signals: Dict) -> List[RCADiagnosis]:
        """Case 6: Safety failure.
        IF toxicity ↓ OR bias ↓ → safety problem
        """
        scores = signals["scores"]
        toxicity = scores.get("toxicity", None)
        bias = scores.get("bias", None)

        evidence = []
        failed = []
        confidence = 0.0

        if toxicity is not None and toxicity < self.LOW_THRESHOLD:
            evidence.append(f"Toxicity score is low ({toxicity:.0f}%) — response contains harmful or inappropriate content")
            failed.append("toxicity")
            confidence += 0.5

        if bias is not None and bias < self.LOW_THRESHOLD:
            evidence.append(f"Bias score is low ({bias:.0f}%) — response shows unfair bias")
            failed.append("bias")
            confidence += 0.4

        if not failed:
            return []

        confidence = min(confidence, 1.0)

        return [RCADiagnosis(
            root_cause="safety_failure",
            category="Safety",
            confidence=round(confidence, 2),
            evidence=evidence,
            recommendation="CRITICAL: Add safety guardrails. Implement content filtering, add safety system prompts, or use a moderation layer before returning responses.",
            failed_metrics=failed,
        )]

    def _check_robustness_failure(self, signals: Dict) -> List[RCADiagnosis]:
        """Case 7: Robustness failure.
        IF failure_recovery ↓ OR node_success_rate ↓ → robustness problem
        """
        scores = signals["scores"]
        failure_recovery = scores.get("failure_recovery", None)
        node_success = scores.get("node_success_rate", None)
        step_count = scores.get("step_count_limit", None)

        evidence = []
        failed = []
        confidence = 0.0

        if failure_recovery is not None and failure_recovery < self.LOW_THRESHOLD:
            evidence.append(f"Failure recovery is low ({failure_recovery:.0f}%) — agent crashes instead of recovering from errors")
            failed.append("failure_recovery")
            confidence += 0.35

        if node_success is not None and node_success < self.LOW_THRESHOLD:
            evidence.append(f"Node success rate is low ({node_success:.0f}%) — some pipeline steps are failing")
            failed.append("node_success_rate")
            confidence += 0.3

        if step_count is not None and step_count < self.LOW_THRESHOLD:
            evidence.append(f"Step count exceeded limit ({step_count:.0f}%) — agent may be looping")
            failed.append("step_count_limit")
            confidence += 0.25

        # Trace evidence
        if signals["trace_errors"]:
            error_details = []
            for err in signals["trace_errors"][:3]:  # max 3
                node = err.get("node", "?")
                error_msg = err.get("error", err.get("result", "?"))
                error_details.append(f"{node}: {error_msg}")
            evidence.append(f"Trace errors: {'; '.join(error_details)}")
            confidence += 0.1

        if not failed:
            return []

        confidence = min(confidence, 1.0)

        return [RCADiagnosis(
            root_cause="robustness_failure",
            category="Robustness",
            confidence=round(confidence, 2),
            evidence=evidence,
            recommendation="Add error handling: implement try/catch in agent nodes, add fallback responses, or limit maximum execution steps to prevent loops.",
            failed_metrics=failed,
        )]

    # ------------------------------------------------------------------
    # Summary builder
    # ------------------------------------------------------------------

    def _build_summary(self, diagnoses: List[RCADiagnosis], signals: Dict) -> str:
        """Build a human-readable summary of all diagnoses."""
        if not diagnoses:
            return "No root causes identified."

        parts = []
        for d in diagnoses:
            parts.append(f"[{d.category}] {d.root_cause} (confidence: {d.confidence:.0%})")

        primary = diagnoses[0]
        summary = f"Primary root cause: {primary.root_cause} ({primary.category}, {primary.confidence:.0%} confidence). "
        if len(diagnoses) > 1:
            others = [f"{d.root_cause}" for d in diagnoses[1:]]
            summary += f"Contributing factors: {', '.join(others)}. "
        summary += f"Recommendation: {primary.recommendation}"

        return summary


# Module-level singleton for easy import
rca_agent = RCAAgent()
