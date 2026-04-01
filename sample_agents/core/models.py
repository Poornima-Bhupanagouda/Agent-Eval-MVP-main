"""
Data models for the multi-agent system.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class AgentRole(Enum):
    """Roles that agents can take."""
    PLANNER = "planner"
    RESEARCHER = "researcher"
    SYNTHESIZER = "synthesizer"
    CRITIC = "critic"


@dataclass
class AgentMessage:
    """A message in the agent conversation."""
    role: str  # "user", "assistant", "system"
    content: str
    agent_name: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResponse:
    """Response from a single agent."""
    agent_name: str
    agent_role: str
    content: str
    reasoning: Optional[str] = None
    confidence: float = 1.0
    tokens_used: int = 0
    latency_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "content": self.content,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
        }


@dataclass
class WorkflowResult:
    """Result from a complete multi-agent workflow."""
    workflow_id: str
    query: str
    final_response: str
    agent_responses: List[AgentResponse] = field(default_factory=list)
    total_tokens: int = 0
    total_latency_ms: int = 0
    success: bool = True
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "query": self.query,
            "final_response": self.final_response,
            "agent_responses": [r.to_dict() for r in self.agent_responses],
            "total_tokens": self.total_tokens,
            "total_latency_ms": self.total_latency_ms,
            "success": self.success,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class ResearchPlan:
    """A structured research plan from the Planner agent."""
    main_question: str
    sub_questions: List[str]
    key_topics: List[str]
    approach: str


@dataclass
class ResearchFindings:
    """Findings from the Researcher agent."""
    topic: str
    findings: List[str]
    sources_needed: List[str]
    confidence: float


@dataclass
class SynthesizedAnswer:
    """Final synthesized answer from the Synthesizer agent."""
    summary: str
    detailed_answer: str
    key_points: List[str]
    limitations: List[str]
    confidence: float
