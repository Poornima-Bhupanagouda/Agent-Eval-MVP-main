"""
Multi-Agent Orchestrator

Manages the workflow between multiple agents, handling:
- Agent sequencing
- Message passing
- Result aggregation
- Error handling
- Per-agent model selection via LLM Gateway
"""

import uuid
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from sample_agents.core.models import (
    AgentResponse,
    WorkflowResult,
    AgentMessage,
)
from sample_agents.core.llm_client import LLMClient


@dataclass
class Agent:
    """
    Base agent configuration with model selection.

    Each agent can use a different LLM model based on their needs:
    - Planner: Fast model for quick analysis
    - Researcher: Capable model for detailed research
    - Synthesizer: Creative model for synthesis
    - Critic: Analytical model for review
    """
    name: str
    role: str
    system_prompt: str
    temperature: float = 0.7
    max_tokens: int = 2000
    model: Optional[str] = None  # Per-agent model override


class AgentOrchestrator:
    """
    Orchestrates multi-agent workflows with per-agent model selection.

    Supports:
    - Sequential agent execution
    - Context passing between agents
    - Result aggregation
    - Per-agent LLM model selection via LLM Gateway
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        default_model: Optional[str] = None,
    ):
        """
        Initialize orchestrator with LLM client.

        Args:
            llm_client: Optional pre-configured LLM client
            default_model: Default model for agents without specific model
        """
        self.default_llm_client = llm_client or LLMClient()
        self.default_model = default_model or self.default_llm_client.model
        self.agents: Dict[str, Agent] = {}
        self.agent_clients: Dict[str, LLMClient] = {}  # Per-agent LLM clients
        self.conversation_history: List[AgentMessage] = []

    def register_agent(self, agent: Agent) -> None:
        """
        Register an agent with the orchestrator.

        If the agent has a specific model configured, creates a dedicated
        LLM client for that agent using the LLM Gateway.
        """
        self.agents[agent.name] = agent

        # Create per-agent LLM client if model is specified
        if agent.model and agent.model != self.default_model:
            self.agent_clients[agent.name] = LLMClient(model=agent.model)

    def _get_client_for_agent(self, agent_name: str) -> LLMClient:
        """Get the LLM client for a specific agent."""
        if agent_name in self.agent_clients:
            return self.agent_clients[agent_name]
        return self.default_llm_client

    async def run_agent(
        self,
        agent_name: str,
        user_input: str,
        context: Optional[str] = None,
        json_mode: bool = False,
    ) -> AgentResponse:
        """
        Run a single agent with the given input.

        Each agent uses its configured model via the LLM Gateway.
        This enables autonomous execution with per-agent model selection.

        Args:
            agent_name: Name of the registered agent
            user_input: The input/query for the agent
            context: Optional additional context
            json_mode: Whether to request JSON output

        Returns:
            AgentResponse with the agent's output
        """
        if agent_name not in self.agents:
            raise ValueError(f"Agent '{agent_name}' not registered")

        agent = self.agents[agent_name]
        llm_client = self._get_client_for_agent(agent_name)
        start_time = time.time()

        # Build messages
        messages = [
            {"role": "system", "content": agent.system_prompt},
        ]

        if context:
            messages.append({
                "role": "user",
                "content": f"Context from previous agents:\n{context}\n\nUser query: {user_input}"
            })
        else:
            messages.append({"role": "user", "content": user_input})

        # Call LLM via Gateway
        response = await llm_client.chat(
            messages=messages,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            json_mode=json_mode,
        )

        latency_ms = int((time.time() - start_time) * 1000)

        # Record in conversation history
        self.conversation_history.append(AgentMessage(
            role="assistant",
            content=response.content,
            agent_name=agent_name,
            metadata={
                "tokens": response.tokens_used,
                "model": llm_client.model,
            },
        ))

        return AgentResponse(
            agent_name=agent_name,
            agent_role=agent.role,
            content=response.content,
            tokens_used=response.tokens_used,
            latency_ms=latency_ms,
            metadata={"model": llm_client.model},
        )

    async def run_workflow(
        self,
        query: str,
        agent_sequence: List[str],
        pass_context: bool = True,
    ) -> WorkflowResult:
        """
        Run a complete workflow through multiple agents.

        Args:
            query: The initial user query
            agent_sequence: List of agent names to run in order
            pass_context: Whether to pass previous agent outputs as context

        Returns:
            WorkflowResult with all agent responses
        """
        workflow_id = str(uuid.uuid4())[:8]
        self.conversation_history = []
        agent_responses: List[AgentResponse] = []
        accumulated_context = ""
        total_tokens = 0
        total_latency = 0

        try:
            for agent_name in agent_sequence:
                # Build context from previous agents
                context = accumulated_context if pass_context and accumulated_context else None

                # Run agent
                response = await self.run_agent(
                    agent_name=agent_name,
                    user_input=query,
                    context=context,
                )

                agent_responses.append(response)
                total_tokens += response.tokens_used
                total_latency += response.latency_ms

                # Accumulate context
                if pass_context:
                    accumulated_context += f"\n\n[{agent_name.upper()}]:\n{response.content}"

            # Final response is from the last agent
            final_response = agent_responses[-1].content if agent_responses else ""

            return WorkflowResult(
                workflow_id=workflow_id,
                query=query,
                final_response=final_response,
                agent_responses=agent_responses,
                total_tokens=total_tokens,
                total_latency_ms=total_latency,
                success=True,
            )

        except Exception as e:
            return WorkflowResult(
                workflow_id=workflow_id,
                query=query,
                final_response="",
                agent_responses=agent_responses,
                total_tokens=total_tokens,
                total_latency_ms=total_latency,
                success=False,
                error=str(e),
            )

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.conversation_history = []
