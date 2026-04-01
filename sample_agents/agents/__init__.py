"""Individual agents for the multi-agent system."""

from sample_agents.agents.research_assistant import ResearchAssistant
from sample_agents.agents.prompts import PLANNER_PROMPT, RESEARCHER_PROMPT, SYNTHESIZER_PROMPT, CRITIC_PROMPT

__all__ = [
    "ResearchAssistant",
    "PLANNER_PROMPT",
    "RESEARCHER_PROMPT",
    "SYNTHESIZER_PROMPT",
    "CRITIC_PROMPT",
]
