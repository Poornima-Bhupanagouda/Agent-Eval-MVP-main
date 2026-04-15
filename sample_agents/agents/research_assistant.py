"""
Research Assistant - Multi-Agent Workflow

A complete multi-agent system that:
1. Plans research approach (Planner Agent)
2. Gathers information (Researcher Agent)
3. Synthesizes findings (Synthesizer Agent)
4. Optionally reviews quality (Critic Agent)

Uses sequential execution for traceable pipeline.
Each agent can use a different LLM model based on its role,
all connected via the LLM Gateway with OAuth2 authentication.
"""

import os
import time
import uuid
from typing import Optional, Dict, List
from sample_agents.core.orchestrator import AgentOrchestrator, Agent
from sample_agents.core.llm_client import LLMClient
from sample_agents.core.models import WorkflowResult, AgentResponse
from sample_agents.agents.prompts import (
    PLANNER_PROMPT,
    RESEARCHER_PROMPT,
    SYNTHESIZER_PROMPT,
    CRITIC_PROMPT,
)



# Default model configurations per agent role
# Users can override via environment variables
DEFAULT_AGENT_MODELS = {
    "planner": os.environ.get("PLANNER_MODEL"),      # Fast model for planning
    "researcher": os.environ.get("RESEARCHER_MODEL"), # Capable model for research
    "synthesizer": os.environ.get("SYNTHESIZER_MODEL"), # Creative model for synthesis
    "critic": os.environ.get("CRITIC_MODEL"),         # Analytical model for review
}


class ResearchAssistant:
    """
    Multi-agent research assistant that combines multiple specialized agents
    to provide comprehensive answers to user queries.

    Each agent uses the LLM Gateway with OAuth2 authentication and can be
    configured to use different models based on their specialized needs:

    - Planner: Uses a fast model for quick analysis (e.g., gpt-4o-mini)
    - Researcher: Uses a capable model for detailed research (e.g., gpt-4o)
    - Synthesizer: Uses a creative model for synthesis (e.g., gpt-4o)
    - Critic: Uses an analytical model for review (e.g., gpt-4o)

    Workflow:
    1. Planner: Analyzes query and creates research plan
    2. Researcher: Gathers detailed information
    3. Synthesizer: Combines findings into coherent answer
    4. Critic (optional): Reviews and validates the answer
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        include_critic: bool = False,
        model: Optional[str] = None,
        agent_models: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the Research Assistant.

        Args:
            llm_client: Optional pre-configured LLM client (uses LLM Gateway)
            include_critic: Whether to include the critic review step
            model: Optional default model override for all agents
            agent_models: Optional dict mapping agent names to specific models
        """
        self.llm_client = llm_client or LLMClient(model=model)
        self.orchestrator = AgentOrchestrator(
            llm_client=self.llm_client,
            default_model=model or self.llm_client.model,
        )
        self.include_critic = include_critic

        # Merge default models with any provided overrides
        self.agent_models = {**DEFAULT_AGENT_MODELS}
        if agent_models:
            self.agent_models.update(agent_models)

        # Register agents with their specific models
        self._register_agents()

    def _register_agents(self) -> None:
        """
        Register all agents with the orchestrator.

        Each agent is configured with its specific model via the LLM Gateway.
        """

        # Planner Agent - breaks down queries
        # Uses fast model for quick analysis
        self.orchestrator.register_agent(Agent(
            name="planner",
            role="planner",
            system_prompt=PLANNER_PROMPT,
            temperature=0.3,  # More deterministic planning
            max_tokens=1000,
            model=self.agent_models.get("planner"),
        ))

        # Researcher Agent - gathers information
        # Uses capable model for detailed research
        self.orchestrator.register_agent(Agent(
            name="researcher",
            role="researcher",
            system_prompt=RESEARCHER_PROMPT,
            temperature=0.5,
            max_tokens=2000,
            model=self.agent_models.get("researcher"),
        ))

        # Synthesizer Agent - creates final answer
        # Uses creative model for synthesis
        self.orchestrator.register_agent(Agent(
            name="synthesizer",
            role="synthesizer",
            system_prompt=SYNTHESIZER_PROMPT,
            temperature=0.7,
            max_tokens=2000,
            model=self.agent_models.get("synthesizer"),
        ))

        # Critic Agent - reviews quality
        # Uses analytical model for review
        self.orchestrator.register_agent(Agent(
            name="critic",
            role="critic",
            system_prompt=CRITIC_PROMPT,
            temperature=0.3,
            max_tokens=1000,
            model=self.agent_models.get("critic"),
        ))

    async def research(self, query: str) -> WorkflowResult:
        """
        Run the full research workflow.
        Planner → Researcher → Synthesizer (optionally + Critic).
        """
        agent_sequence = ["planner", "researcher", "synthesizer"]
        if self.include_critic:
            agent_sequence.append("critic")
        return await self._run_pipeline_workflow(query, agent_sequence, pass_context=True)

    async def quick_answer(self, query: str) -> WorkflowResult:
        """Quick single-agent answer using only the synthesizer."""
        return await self._run_pipeline_workflow(query, ["synthesizer"], pass_context=False)

    async def research_with_review(self, query: str) -> WorkflowResult:
        """Full research with mandatory critic review."""
        return await self._run_pipeline_workflow(
            query, ["planner", "researcher", "synthesizer", "critic"], pass_context=True,
        )

    async def _run_pipeline_workflow(
        self, query: str, agent_sequence: List[str], pass_context: bool = True,
    ) -> WorkflowResult:
        """
        Build and run a traced pipeline for the given agent sequence.
        Each agent in the sequence becomes a node in the pipeline.
        """
        orchestrator = self.orchestrator
        workflow_id = str(uuid.uuid4())[:8]

        # Run each agent in sequence
        state = {"query": query, "intermediate": {}, "tool_calls": [], "output": "", "errors": []}

        for agent_name in agent_sequence:
            state = dict(state)
            state["intermediate"] = dict(state.get("intermediate", {}))
            state["tool_calls"] = list(state.get("tool_calls", []))

            # Build context from previous agents
            context = None
            if pass_context:
                prev_outputs = state["intermediate"].get("accumulated_context", "")
                if prev_outputs:
                    context = prev_outputs

            response = await orchestrator.run_agent(
                agent_name=agent_name,
                user_input=state["query"],
                context=context,
            )

            # Store response
            responses = list(state["intermediate"].get("agent_responses", []))
            responses.append({
                "agent_name": response.agent_name,
                "agent_role": response.agent_role,
                "content": response.content,
                "tokens_used": response.tokens_used,
                "latency_ms": response.latency_ms,
                "metadata": response.metadata,
            })
            state["intermediate"]["agent_responses"] = responses

            # Track tool call
            state["tool_calls"].append({
                "name": "run_agent",
                "args": {"agent": agent_name, "model": response.metadata.get("model", "")},
            })

            # Accumulate context
            if pass_context:
                acc = state["intermediate"].get("accumulated_context", "")
                acc += f"\n\n[{agent_name.upper()}]:\n{response.content}"
                state["intermediate"]["accumulated_context"] = acc

            # Last agent's output becomes the final output
            state["output"] = response.content

        # --- Convert to WorkflowResult ---
        raw_responses = state.get("intermediate", {}).get("agent_responses", [])
        agent_responses = [
            AgentResponse(
                agent_name=r["agent_name"],
                agent_role=r["agent_role"],
                content=r["content"],
                tokens_used=r["tokens_used"],
                latency_ms=r["latency_ms"],
                metadata=r.get("metadata", {}),
            )
            for r in raw_responses
        ]
        total_tokens = sum(r.tokens_used for r in agent_responses)
        total_latency = sum(r.latency_ms for r in agent_responses)

        return WorkflowResult(
            workflow_id=workflow_id,
            query=query,
            final_response=result.get("output", ""),
            agent_responses=agent_responses,
            total_tokens=total_tokens,
            total_latency_ms=total_latency,
            success=True,
        )
