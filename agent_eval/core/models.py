"""
Data models for Lilly Agent Eval.

Simple, minimal data classes for tests, suites, results, and batches.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
import uuid


def generate_id() -> str:
    """Generate a short unique ID."""
    return uuid.uuid4().hex[:12]


@dataclass
class Test:
    """A single test case."""
    input: str
    id: str = field(default_factory=generate_id)
    suite_id: Optional[str] = None
    name: Optional[str] = None
    expected: Optional[str] = None
    context: Optional[List[str]] = None
    metrics: Optional[List[str]] = None
    expected_tool_calls: Optional[List[Dict]] = None  # For tool-use validation
    trajectory: Optional[Dict] = None  # {match_type, expected_calls, check_args}
    rubrics: Optional[List[str]] = None  # Custom evaluation criteria
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "suite_id": self.suite_id,
            "name": self.name,
            "input": self.input,
            "expected": self.expected,
            "context": self.context,
            "metrics": self.metrics,
            "expected_tool_calls": self.expected_tool_calls,
            "trajectory": self.trajectory,
            "rubrics": self.rubrics,
            "created_at": self.created_at,
        }


@dataclass
class Suite:
    """A collection of test cases."""
    name: str
    id: str = field(default_factory=generate_id)
    description: Optional[str] = None
    endpoint: Optional[str] = None
    tests: List[Test] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "endpoint": self.endpoint,
            "test_count": len(self.tests),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class EvalMetric:
    """A single evaluation metric result."""
    metric: str
    score: float  # 0-100
    passed: bool
    reason: str
    details: Optional[dict] = None
    scored_by: str = "heuristic"  # "deepeval" or "heuristic"


@dataclass
class Result:
    """An evaluation result."""
    endpoint: str
    input: str
    output: str
    score: float  # 0-100
    passed: bool
    latency_ms: int
    evaluations: List[EvalMetric]
    id: str = field(default_factory=generate_id)
    test_id: Optional[str] = None
    suite_id: Optional[str] = None
    batch_id: Optional[str] = None
    expected: Optional[str] = None
    trajectory_result: Optional[Dict] = None  # TrajectoryResult as dict
    rubric_results: Optional[List[Dict]] = None  # [{rubric, matched, keywords}]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        d = {
            "id": self.id,
            "test_id": self.test_id,
            "suite_id": self.suite_id,
            "batch_id": self.batch_id,
            "endpoint": self.endpoint,
            "input": self.input,
            "output": self.output,
            "expected": self.expected,
            "score": round(self.score, 1) if self.score is not None else 0,
            "passed": self.passed,
            "latency_ms": self.latency_ms,
            "evaluations": [
                {"metric": e.metric, "score": round(e.score, 1), "passed": e.passed, "reason": e.reason, "scored_by": getattr(e, 'scored_by', 'heuristic')}
                for e in self.evaluations
            ],
            "created_at": self.created_at,
        }
        if self.trajectory_result:
            d["trajectory_result"] = self.trajectory_result
        if self.rubric_results:
            d["rubric_results"] = self.rubric_results
        return d


@dataclass
class Batch:
    """A batch evaluation run."""
    name: str
    id: str = field(default_factory=generate_id)
    total_tests: int = 0
    passed_tests: int = 0
    avg_score: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "avg_score": self.avg_score,
            "pass_rate": (self.passed_tests / self.total_tests * 100) if self.total_tests > 0 else 0,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


# === Multi-Agent Testing Models ===

@dataclass
class RegisteredAgent:
    """A registered agent with its profile and configuration."""
    name: str
    endpoint: str
    id: str = field(default_factory=generate_id)
    description: Optional[str] = None
    agent_type: str = "simple"  # "rag", "conversational", "tool_using", "simple"
    domain: str = "general"
    capabilities: Optional[List[str]] = None
    # Authentication
    auth_type: str = "none"  # "none", "bearer_token", "api_key", "basic_auth"
    auth_config: Optional[dict] = None  # Stores auth details
    # Metadata
    version: Optional[str] = None  # e.g., "v1.2.0" or "canary"
    tags: Optional[List[str]] = None  # e.g., ["production", "staging"]
    is_active: bool = True
    last_tested_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "endpoint": self.endpoint,
            "description": self.description,
            "agent_type": self.agent_type,
            "domain": self.domain,
            "capabilities": self.capabilities,
            "auth_type": self.auth_type,
            "version": self.version,
            "tags": self.tags,
            "is_active": self.is_active,
            "last_tested_at": self.last_tested_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ABComparison:
    """An A/B comparison between two agents."""
    name: str
    agent_a_id: str  # Control agent
    agent_b_id: str  # Treatment agent
    id: str = field(default_factory=generate_id)
    suite_id: Optional[str] = None  # Test suite to use
    status: str = "pending"  # "pending", "running", "completed", "failed"
    # Results
    agent_a_results: Optional[dict] = None  # {"total": N, "passed": N, "avg_score": N, "avg_latency": N}
    agent_b_results: Optional[dict] = None
    winner: Optional[str] = None  # "A", "B", "tie", or None
    p_value: Optional[float] = None
    effect_size: Optional[float] = None
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "agent_a_id": self.agent_a_id,
            "agent_b_id": self.agent_b_id,
            "suite_id": self.suite_id,
            "status": self.status,
            "agent_a_results": self.agent_a_results,
            "agent_b_results": self.agent_b_results,
            "winner": self.winner,
            "p_value": self.p_value,
            "effect_size": self.effect_size,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


@dataclass
class MultiAgentBatch:
    """A batch comparison run across multiple agents."""
    name: str
    agent_ids: List[str]
    id: str = field(default_factory=generate_id)
    suite_id: Optional[str] = None
    status: str = "pending"  # "pending", "running", "completed"
    # Results per agent: {agent_id: {total, passed, avg_score, avg_latency}}
    agent_results: Dict[str, dict] = field(default_factory=dict)
    best_agent_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "agent_ids": self.agent_ids,
            "suite_id": self.suite_id,
            "status": self.status,
            "agent_results": self.agent_results,
            "best_agent_id": self.best_agent_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


# === Chain Testing Models ===

@dataclass
class ChainStep:
    """A single step in an agent chain."""
    agent_id: str
    order: int = 0
    input_mapping: str = "previous_output"  # "direct", "previous_output", "template"
    input_template: Optional[str] = None  # Template for input transformation
    expected_routing: Optional[str] = None  # Expected agent to route to (for routing verification)
    expected_output: Optional[str] = None  # Expected output for per-step evaluation
    expected_tool_calls: Optional[List[Dict]] = None  # Expected tools this agent should call
    metrics: Optional[List[str]] = None  # Metrics to evaluate this step
    context: Optional[List[str]] = None  # Context for RAG steps

    def to_dict(self) -> dict:
        d = {
            "agent_id": self.agent_id,
            "order": self.order,
            "input_mapping": self.input_mapping,
            "input_template": self.input_template,
            "expected_routing": self.expected_routing,
        }
        if self.expected_output is not None:
            d["expected_output"] = self.expected_output
        if self.expected_tool_calls is not None:
            d["expected_tool_calls"] = self.expected_tool_calls
        if self.metrics is not None:
            d["metrics"] = self.metrics
        if self.context is not None:
            d["context"] = self.context
        return d


@dataclass
class AgentChain:
    """A chain of agents for orchestrator testing."""
    name: str
    steps: List[ChainStep]
    id: str = field(default_factory=generate_id)
    description: Optional[str] = None
    fail_fast: bool = False  # Stop on first failure
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "step_count": len(self.steps),
            "fail_fast": self.fail_fast,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass
class ChainStepResult:
    """Result of a single step in a chain execution."""
    agent_id: str
    agent_name: str
    input: str
    output: str
    latency_ms: int
    success: bool
    error: Optional[str] = None
    evaluations: Optional[List[Dict]] = None  # [{metric, score, passed, reason}]
    tool_calls: Optional[List[Dict]] = None  # Captured tool calls from response
    score: Optional[float] = None  # Average score across evaluations

    def to_dict(self) -> dict:
        d = {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "input": self.input,
            "output": self.output,
            "latency_ms": self.latency_ms,
            "success": self.success,
            "error": self.error,
        }
        if self.evaluations is not None:
            d["evaluations"] = self.evaluations
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
        if self.score is not None:
            d["score"] = self.score
        return d


@dataclass
class ChainResult:
    """Result of running a test through an agent chain."""
    chain_id: str
    test_input: str
    final_output: str
    step_results: List[ChainStepResult]
    id: str = field(default_factory=generate_id)
    total_latency_ms: int = 0
    success: bool = True
    routing_correct: Optional[bool] = None  # For routing verification
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "chain_id": self.chain_id,
            "test_input": self.test_input,
            "final_output": self.final_output,
            "step_results": [s.to_dict() for s in self.step_results],
            "total_latency_ms": self.total_latency_ms,
            "success": self.success,
            "routing_correct": self.routing_correct,
            "created_at": self.created_at,
        }


@dataclass
class ChainRun:
    """A complete chain test run (can include multiple tests)."""
    chain_id: str
    name: str
    id: str = field(default_factory=generate_id)
    suite_id: Optional[str] = None
    status: str = "pending"  # "pending", "running", "completed", "failed"
    total_tests: int = 0
    passed_tests: int = 0
    avg_latency_ms: float = 0.0
    routing_accuracy: Optional[float] = None  # Percentage of correct routings
    results: List[ChainResult] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "chain_id": self.chain_id,
            "name": self.name,
            "suite_id": self.suite_id,
            "status": self.status,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "pass_rate": (self.passed_tests / self.total_tests * 100) if self.total_tests > 0 else 0,
            "avg_latency_ms": self.avg_latency_ms,
            "routing_accuracy": self.routing_accuracy,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


# === Trajectory & Component Scoring Models ===

@dataclass
class TrajectoryResult:
    """Result of comparing actual vs expected tool-call trajectory."""
    score: float  # 0.0 or 1.0 (binary per ADK convention), scaled to 0-100
    match_type: str  # EXACT, IN_ORDER, ANY_ORDER
    matched: bool
    expected_calls: List[Dict]
    actual_calls: List[Dict]
    details: str = ""
    per_call_match: Optional[List[Dict]] = None  # [{expected, actual, matched}]

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "match_type": self.match_type,
            "matched": self.matched,
            "expected_calls": self.expected_calls,
            "actual_calls": self.actual_calls,
            "details": self.details,
            "per_call_match": self.per_call_match,
        }


@dataclass
class InvocationScore:
    """Per-step score breakdown (component-level scoring)."""
    step_index: int
    agent_name: str
    input_text: str
    output_text: str
    latency_ms: int
    score: float
    passed: bool
    evaluations: List[Dict]
    tool_calls: Optional[List[Dict]] = None
    trajectory_result: Optional[Dict] = None
    rubric_results: Optional[List[Dict]] = None
    contribution: Optional[float] = None

    def to_dict(self) -> dict:
        d = {
            "step_index": self.step_index,
            "agent_name": self.agent_name,
            "input": self.input_text,
            "output": self.output_text,
            "latency_ms": self.latency_ms,
            "score": self.score,
            "passed": self.passed,
            "evaluations": self.evaluations,
        }
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.trajectory_result:
            d["trajectory_result"] = self.trajectory_result
        if self.rubric_results:
            d["rubric_results"] = self.rubric_results
        if self.contribution is not None:
            d["contribution"] = self.contribution
        return d


# === Workflow Models ===

@dataclass
class WorkflowAgent:
    """An agent definition within a workflow."""
    name: str
    endpoint: str
    health_path: str = "/health"
    role: str = "sub_agent"  # "orchestrator" or "sub_agent"
    tags: Optional[List[str]] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "endpoint": self.endpoint,
            "health_path": self.health_path,
            "role": self.role,
            "tags": self.tags,
        }


@dataclass
class Workflow:
    """A multi-agent workflow definition."""
    name: str
    orchestrator: WorkflowAgent
    sub_agents: List[WorkflowAgent]
    id: str = field(default_factory=generate_id)
    description: Optional[str] = None
    test_suite_path: Optional[str] = None
    source: str = "yaml"  # "yaml" or "ui"
    source_file: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "orchestrator": self.orchestrator.to_dict(),
            "sub_agents": [a.to_dict() for a in self.sub_agents],
            "agent_count": 1 + len(self.sub_agents),
            "test_suite_path": self.test_suite_path,
            "source": self.source,
            "source_file": self.source_file,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

@dataclass
class ConversationTurn:
    """A single turn in a multi-turn conversation test."""
    role: str  # "user" or "expected_assistant"
    content: str
    expected: Optional[str] = None  # Expected response for user turns
    check_metrics: Optional[List[str]] = None  # Metrics to check on this turn
    expected_tool_calls: Optional[List[Dict]] = None  # Expected tool calls

    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "content": self.content,
            "expected": self.expected,
            "check_metrics": self.check_metrics,
            "expected_tool_calls": self.expected_tool_calls,
        }


@dataclass
class ConversationTurnResult:
    """Result of executing one turn in a conversation."""
    turn_index: int
    input: str
    output: str
    latency_ms: int
    evaluations: List[EvalMetric]
    score: float
    passed: bool
    tool_calls: Optional[List[Dict]] = None  # Actual tool calls made
    tool_call_correct: Optional[bool] = None  # Did tools match expected?
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "turn_index": self.turn_index,
            "input": self.input,
            "output": self.output,
            "latency_ms": self.latency_ms,
            "evaluations": [
                {"metric": e.metric, "score": e.score, "passed": e.passed, "reason": e.reason}
                for e in self.evaluations
            ],
            "score": self.score,
            "passed": self.passed,
            "tool_calls": self.tool_calls,
            "tool_call_correct": self.tool_call_correct,
            "error": self.error,
        }


@dataclass
class ConversationTest:
    """A multi-turn conversation test case."""
    name: str
    turns: List[ConversationTurn]
    id: str = field(default_factory=generate_id)
    suite_id: Optional[str] = None
    description: Optional[str] = None
    endpoint: Optional[str] = None
    context: Optional[List[str]] = None  # Shared context for all turns
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "suite_id": self.suite_id,
            "name": self.name,
            "description": self.description,
            "endpoint": self.endpoint,
            "turns": [t.to_dict() for t in self.turns],
            "turn_count": len(self.turns),
            "context": self.context,
            "created_at": self.created_at,
        }


@dataclass
class ConversationResult:
    """Result of running a multi-turn conversation test."""
    conversation_id: str
    endpoint: str
    turn_results: List[ConversationTurnResult]
    id: str = field(default_factory=generate_id)
    total_turns: int = 0
    passed_turns: int = 0
    avg_score: float = 0.0
    total_latency_ms: int = 0
    coherence_score: float = 0.0  # Cross-turn consistency
    context_retention_score: float = 0.0  # Remembers previous turns
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "endpoint": self.endpoint,
            "turn_results": [t.to_dict() for t in self.turn_results],
            "total_turns": self.total_turns,
            "passed_turns": self.passed_turns,
            "pass_rate": (self.passed_turns / self.total_turns * 100) if self.total_turns > 0 else 0,
            "avg_score": self.avg_score,
            "total_latency_ms": self.total_latency_ms,
            "coherence_score": self.coherence_score,
            "context_retention_score": self.context_retention_score,
            "created_at": self.created_at,
        }
