"""
Test Templates for Lilly Agent Eval.

Pre-built test template collections by agent type.
Loads YAML template packs and provides programmatic access.
"""

import os
import yaml
import logging
from typing import List, Dict, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Template pack metadata
# NOTE: Keep in sync with WIZARD_TEMPLATE_PACKS in index.html (wizard preview)
TEMPLATE_PACKS = {
    "rag_starter": {
        "name": "RAG Agent Starter",
        "description": "12 tests for RAG evaluation: faithfulness, hallucination, context quality",
        "agent_type": "rag",
        "test_count": 12,
        "focus": ["faithfulness", "hallucination", "contextual_relevancy", "precision_at_k"],
        "file": "rag_starter.yaml",
    },
    "safety_suite": {
        "name": "Safety & Compliance",
        "description": "15 tests for safety: toxicity, bias, prompt injection, jailbreak, PII",
        "agent_type": "safety",
        "test_count": 15,
        "focus": ["toxicity", "bias", "task_completion"],
        "file": "safety_suite.yaml",
    },
    "conversation_flow": {
        "name": "Conversational Agent",
        "description": "8 multi-turn conversation tests for context retention and coherence",
        "agent_type": "conversational",
        "test_count": 8,
        "focus": ["coherence", "context_retention", "task_completion"],
        "file": "conversation_flow.yaml",
    },
    "tool_use_validation": {
        "name": "Tool-Using Agent",
        "description": "10 tests for tool calling: selection, args accuracy, sequencing",
        "agent_type": "tool_using",
        "test_count": 10,
        "focus": ["tool_correctness", "tool_args_accuracy", "tool_sequence"],
        "file": "tool_use_validation.yaml",
    },
    "performance_sla": {
        "name": "Performance & Reliability",
        "description": "6 tests for latency SLA, edge cases, and reliability",
        "agent_type": "performance",
        "test_count": 6,
        "focus": ["task_completion", "answer_relevancy"],
        "file": "performance_sla.yaml",
    },
    "general_agent": {
        "name": "General Agent",
        "description": "10 tests for overall quality: relevancy, task completion, basic safety",
        "agent_type": "general",
        "test_count": 10,
        "focus": ["answer_relevancy", "task_completion", "toxicity"],
        "file": "general_agent.yaml",
    },
    "orchestrator_chain": {
        "name": "Multi-Agent Orchestrator",
        "description": "8 tests for orchestrator chains: routing, per-step quality, tool validation, context flow",
        "agent_type": "orchestrator",
        "test_count": 8,
        "focus": ["answer_relevancy", "tool_correctness", "tool_sequence", "task_completion"],
        "file": "orchestrator_chain.yaml",
    },
}


def get_templates_dir() -> Path:
    """Get the templates directory path."""
    # Check multiple possible locations
    candidates = [
        Path(__file__).parent.parent.parent / "tests" / "templates",
        Path.cwd() / "tests" / "templates",
    ]
    for p in candidates:
        if p.exists():
            return p
    # Default to first candidate
    return candidates[0]


def list_template_packs() -> List[Dict]:
    """List all available template packs with metadata."""
    templates_dir = get_templates_dir()
    packs = []
    for pack_id, meta in TEMPLATE_PACKS.items():
        pack_info = {
            "id": pack_id,
            "name": meta["name"],
            "description": meta["description"],
            "agent_type": meta["agent_type"],
            "test_count": meta["test_count"],
            "focus_metrics": meta["focus"],
            "available": (templates_dir / meta["file"]).exists(),
        }
        packs.append(pack_info)
    return packs


def load_template_pack(pack_id: str) -> Optional[Dict]:
    """
    Load a template pack by ID.

    Returns the full YAML content as a dict, or None if not found.
    """
    if pack_id not in TEMPLATE_PACKS:
        return None

    templates_dir = get_templates_dir()
    file_path = templates_dir / TEMPLATE_PACKS[pack_id]["file"]

    if not file_path.exists():
        logger.warning(f"Template file not found: {file_path}")
        return None

    try:
        with open(file_path, "r") as f:
            data = yaml.safe_load(f)
        return data
    except Exception as e:
        logger.error(f"Failed to load template {pack_id}: {e}")
        return None


def get_template_tests(pack_id: str) -> List[Dict]:
    """
    Get just the test cases from a template pack.

    Returns a list of test dicts ready to use.
    """
    data = load_template_pack(pack_id)
    if not data:
        return []

    return data.get("tests", [])


def suggest_templates(agent_type: str) -> List[str]:
    """
    Suggest template packs based on agent type.

    Args:
        agent_type: "rag", "conversational", "tool_using", "simple", etc.

    Returns:
        List of recommended pack IDs
    """
    recommendations = []

    # Always recommend general
    recommendations.append("general_agent")

    # Type-specific recommendations
    type_map = {
        "rag": ["rag_starter", "safety_suite"],
        "conversational": ["conversation_flow", "safety_suite"],
        "tool_using": ["tool_use_validation", "orchestrator_chain", "safety_suite"],
        "orchestrator": ["orchestrator_chain", "tool_use_validation", "safety_suite"],
        "simple": ["safety_suite", "performance_sla"],
    }

    for pack_id in type_map.get(agent_type, []):
        if pack_id not in recommendations:
            recommendations.append(pack_id)

    # Always recommend safety
    if "safety_suite" not in recommendations:
        recommendations.append("safety_suite")

    return recommendations
