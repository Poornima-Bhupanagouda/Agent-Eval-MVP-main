"""
Lilly Agent Eval - Simple, Fast Agent Evaluation

A TruLens-inspired evaluation platform for testing AI agents.
"""

__version__ = "3.0.0"

from agent_eval.core.evaluator import Evaluator
from agent_eval.core.executor import Executor
from agent_eval.core.storage import Storage

__all__ = ["Evaluator", "Executor", "Storage"]
