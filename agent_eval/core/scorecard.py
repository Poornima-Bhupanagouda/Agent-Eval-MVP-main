"""
Agent Scorecard for Lilly Agent Eval.

Groups metrics into categories, calculates category scores,
identifies top issues, and provides failure analysis hints.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field


# Metric to category mapping
METRIC_CATEGORIES = {
    "answer_relevancy": "Correctness",
    "similarity": "Correctness",
    "task_completion": "Correctness",
    "toxicity": "Safety",
    "bias": "Safety",
    "faithfulness": "Faithfulness",
    "hallucination": "Faithfulness",
    "contextual_relevancy": "Faithfulness",
    "precision_at_k": "Retrieval",
    "recall_at_k": "Retrieval",
    "mrr": "Retrieval",
    "tool_correctness": "Tool Use",
    "tool_args_accuracy": "Tool Use",
    "tool_sequence": "Tool Use",
    "routing_correctness": "Orchestration",
    "context_flow": "Orchestration",
    "coherence": "Conversation",
    "context_retention": "Conversation",
}

CATEGORY_ORDER = [
    "Correctness",
    "Safety",
    "Faithfulness",
    "Retrieval",
    "Tool Use",
    "Orchestration",
    "Conversation",
]

# Failure pattern -> hint mapping
FAILURE_HINTS = [
    {
        "pattern": {"low": ["faithfulness"], "high": ["answer_relevancy"]},
        "hint": "Agent answers well but not from provided context. Check retrieval pipeline or grounding instructions.",
    },
    {
        "pattern": {"low": ["answer_relevancy"], "high": ["faithfulness"]},
        "hint": "Agent uses context but doesn't address the question. Check prompt template or system instructions.",
    },
    {
        "pattern": {"low": ["tool_correctness"]},
        "hint": "Agent called the wrong tools. Check tool descriptions and routing logic.",
    },
    {
        "pattern": {"low": ["tool_args_accuracy"], "high": ["tool_correctness"]},
        "hint": "Right tool selected but wrong arguments. Check argument extraction and parameter mapping.",
    },
    {
        "pattern": {"low": ["coherence"]},
        "hint": "Agent loses consistency across turns. Check conversation history handling and context window.",
    },
    {
        "pattern": {"low": ["context_retention"]},
        "hint": "Agent forgets earlier information. Check history window size and memory management.",
    },
    {
        "pattern": {"low": ["hallucination"]},
        "hint": "Agent makes up facts not in context. Add stricter grounding instructions or retrieval validation.",
    },
    {
        "pattern": {"low": ["toxicity"]},
        "hint": "Safety guardrails may be bypassed. Test with adversarial inputs and strengthen content filters.",
    },
    {
        "pattern": {"low": ["bias"]},
        "hint": "Responses show potential bias. Review training data and add fairness constraints to prompts.",
    },
    {
        "pattern": {"low": ["task_completion"]},
        "hint": "Agent hedges or refuses to complete tasks. Check system prompt constraints and confidence thresholds.",
    },
    {
        "pattern": {"low": ["precision_at_k"]},
        "hint": "Many irrelevant chunks in retrieved context. Improve embedding model or chunking strategy.",
    },
    {
        "pattern": {"low": ["recall_at_k"]},
        "hint": "Relevant information not being retrieved. Increase retrieval count (top-k) or improve indexing.",
    },
    {
        "pattern": {"low": ["routing_correctness"]},
        "hint": "Orchestrator routing queries to wrong agents. Check routing logic, keywords, or agent descriptions.",
    },
    {
        "pattern": {"low": ["tool_sequence"], "high": ["tool_correctness"]},
        "hint": "Right tools selected but in wrong order. Check orchestrator sequencing and dependency resolution.",
    },
]


@dataclass
class CategoryScore:
    """Score for a metric category."""
    name: str
    score: float
    total_metrics: int
    passed_metrics: int
    metrics: List[Dict]  # [{metric, score, passed, reason}]


@dataclass
class Scorecard:
    """Complete agent scorecard."""
    overall_score: float
    overall_passed: bool
    total_tests: int
    passed_tests: int
    duration_ms: int
    categories: List[CategoryScore]
    top_issues: List[str]
    failure_hints: List[str]
    endpoint: str = ""
    agent_name: str = ""

    def to_dict(self) -> dict:
        return {
            "overall_score": round(self.overall_score, 1),
            "overall_passed": self.overall_passed,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "pass_rate": round(self.passed_tests / self.total_tests * 100, 1) if self.total_tests > 0 else 0,
            "duration_ms": self.duration_ms,
            "categories": [
                {
                    "name": c.name,
                    "score": round(c.score, 1),
                    "total_metrics": c.total_metrics,
                    "passed_metrics": c.passed_metrics,
                    "pass_rate": round(c.passed_metrics / c.total_metrics * 100, 1) if c.total_metrics > 0 else 0,
                    "metrics": c.metrics,
                }
                for c in self.categories
            ],
            "top_issues": self.top_issues,
            "failure_hints": self.failure_hints,
            "endpoint": self.endpoint,
            "agent_name": self.agent_name,
        }


def generate_scorecard(
    results: List[Dict],
    endpoint: str = "",
    agent_name: str = "",
    threshold: float = 70.0,
) -> Scorecard:
    """
    Generate an agent scorecard from evaluation results.

    Args:
        results: List of result dicts, each with 'evaluations' list
                 where each eval has {metric, score, passed, reason}
        endpoint: Agent endpoint URL
        agent_name: Agent name
        threshold: Pass/fail threshold

    Returns:
        Scorecard with categorized scores and insights
    """
    # Collect all metric scores across all results
    metric_scores: Dict[str, List[Dict]] = {}
    total_tests = len(results)
    passed_tests = sum(1 for r in results if r.get("passed", False))
    total_latency = sum(r.get("latency_ms", 0) for r in results)

    for result in results:
        for ev in result.get("evaluations", []):
            metric = ev.get("metric", "")
            if metric not in metric_scores:
                metric_scores[metric] = []
            metric_scores[metric].append({
                "score": ev.get("score", 0),
                "passed": ev.get("passed", False),
                "reason": ev.get("reason", ""),
            })

    # Build category scores
    category_data: Dict[str, List[Dict]] = {}
    for metric, scores in metric_scores.items():
        category = METRIC_CATEGORIES.get(metric, "Other")
        if category not in category_data:
            category_data[category] = []

        avg_score = sum(s["score"] for s in scores) / len(scores) if scores else 0
        passed_count = sum(1 for s in scores if s["passed"])
        total_count = len(scores)

        category_data[category].append({
            "metric": metric,
            "score": round(avg_score, 1),
            "passed": passed_count >= total_count * 0.5,  # majority pass
            "total_runs": total_count,
            "passed_runs": passed_count,
            "reason": scores[-1]["reason"] if scores else "",
        })

    # Build CategoryScore objects in order
    categories = []
    for cat_name in CATEGORY_ORDER:
        if cat_name in category_data:
            metrics = category_data[cat_name]
            cat_score = sum(m["score"] for m in metrics) / len(metrics) if metrics else 0
            cat_passed = sum(1 for m in metrics if m["passed"])
            categories.append(CategoryScore(
                name=cat_name,
                score=cat_score,
                total_metrics=len(metrics),
                passed_metrics=cat_passed,
                metrics=metrics,
            ))

    # Handle "Other" category
    if "Other" in category_data:
        metrics = category_data["Other"]
        cat_score = sum(m["score"] for m in metrics) / len(metrics) if metrics else 0
        cat_passed = sum(1 for m in metrics if m["passed"])
        categories.append(CategoryScore(
            name="Other",
            score=cat_score,
            total_metrics=len(metrics),
            passed_metrics=cat_passed,
            metrics=metrics,
        ))

    # Overall score
    all_metric_scores = [m["score"] for cat in categories for m in cat.metrics]
    overall_score = sum(all_metric_scores) / len(all_metric_scores) if all_metric_scores else 0

    # Top issues: metrics that failed most
    top_issues = _find_top_issues(results, metric_scores)

    # Failure hints
    failure_hints = _generate_failure_hints(metric_scores, threshold)

    return Scorecard(
        overall_score=overall_score,
        overall_passed=overall_score >= threshold,
        total_tests=total_tests,
        passed_tests=passed_tests,
        duration_ms=total_latency,
        categories=categories,
        top_issues=top_issues[:5],
        failure_hints=failure_hints[:5],
        endpoint=endpoint,
        agent_name=agent_name,
    )


def _find_top_issues(results: List[Dict], metric_scores: Dict[str, List[Dict]]) -> List[str]:
    """Find the top failing issues across all results."""
    issues = []

    for metric, scores in metric_scores.items():
        failed = [s for s in scores if not s["passed"]]
        total = len(scores)
        if failed:
            fail_rate = len(failed) / total
            avg_fail_score = sum(s["score"] for s in failed) / len(failed)
            metric_name = metric.replace("_", " ").title()
            issues.append({
                "text": f"{metric_name} failed in {len(failed)}/{total} tests (avg score: {avg_fail_score:.0f})",
                "severity": fail_rate * (100 - avg_fail_score),  # Higher = worse
            })

    issues.sort(key=lambda x: x["severity"], reverse=True)
    return [i["text"] for i in issues]


def _generate_failure_hints(
    metric_scores: Dict[str, List[Dict]],
    threshold: float,
) -> List[str]:
    """Generate actionable failure hints based on metric score patterns."""
    hints = []

    # Calculate avg score per metric
    avg_scores = {}
    for metric, scores in metric_scores.items():
        if scores:
            avg_scores[metric] = sum(s["score"] for s in scores) / len(scores)

    for hint_def in FAILURE_HINTS:
        pattern = hint_def["pattern"]
        matches = True

        # Check "low" metrics (below threshold)
        for metric in pattern.get("low", []):
            if metric not in avg_scores or avg_scores[metric] >= threshold:
                matches = False
                break

        # Check "high" metrics (above threshold) if specified
        if matches and "high" in pattern:
            for metric in pattern["high"]:
                if metric not in avg_scores or avg_scores[metric] < threshold:
                    matches = False
                    break

        if matches:
            hints.append(hint_def["hint"])

    return hints
