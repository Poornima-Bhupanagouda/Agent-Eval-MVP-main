"""
STEP 6 — Self-Healing Agent Unit Tests.

Tests the decision tree, variant generation, scoring, and
end-to-end healing pipeline with mock executor/evaluator.
"""

import sys
import asyncio
sys.path.insert(0, ".")

from agent_eval.core.self_healing import (
    SelfHealingAgent, HealingResult, HealingRecommendation,
    VariantResult, CONFIG_VARIANTS, PROMPT_VARIANTS,
    healing_agent,
)


# ---------------------------------------------------------------------------
# Mock executor and evaluator for testing
# ---------------------------------------------------------------------------

class MockExecutionResult:
    def __init__(self, output="Mock output", latency_ms=500, tool_calls=None, trace=None):
        self.output = output
        self.latency_ms = latency_ms
        self.tool_calls = tool_calls
        self.trace = trace


class MockExecutor:
    """Simulates re-running an agent. Returns different outputs per variant."""
    def __init__(self, responses=None):
        self.call_count = 0
        self.responses = responses or []
        self.calls = []

    async def execute(self, endpoint, input_text, headers=None, context=None):
        self.calls.append({"endpoint": endpoint, "input": input_text, "context": context})
        idx = self.call_count
        self.call_count += 1
        if idx < len(self.responses):
            return self.responses[idx]
        return MockExecutionResult(output=f"Response variant {idx}")


class MockEvalResult:
    def __init__(self, metric, score, passed, reason="", scored_by="heuristic"):
        self.metric = metric
        self.score = score
        self.passed = passed
        self.reason = reason
        self.scored_by = scored_by


class MockEvaluator:
    """Simulates evaluation. Returns progressively better scores."""
    def __init__(self, score_sequence=None):
        self.call_count = 0
        self.score_sequence = score_sequence or []

    def evaluate(self, **kwargs):
        idx = self.call_count
        self.call_count += 1
        if idx < len(self.score_sequence):
            scores = self.score_sequence[idx]
        else:
            # Default: gradual improvement
            base = 50 + idx * 10
            scores = {"faithfulness": min(base, 95), "contextual_relevancy": min(base + 5, 95)}
        return [
            MockEvalResult(metric=m, score=s, passed=s >= 70)
            for m, s in scores.items()
        ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_classify_fix_path():
    """Retrieval → config, prompt → prompt, others → manual."""
    agent = SelfHealingAgent()
    assert agent._classify_fix_path("retrieval_failure") == "config"
    assert agent._classify_fix_path("prompt_failure") == "prompt"
    assert agent._classify_fix_path("planning_failure") == "manual"
    assert agent._classify_fix_path("safety_failure") == "manual"
    assert agent._classify_fix_path("performance_failure") == "manual"
    assert agent._classify_fix_path("memory_failure") == "manual"
    print("PASS: test_classify_fix_path")


def test_generate_config_variants():
    """Config variants should match CONFIG_VARIANTS."""
    agent = SelfHealingAgent()
    variants = agent._generate_variants("config", "retrieval_failure")
    assert len(variants) == len(CONFIG_VARIANTS)
    assert all(v["variant_type"] == "config" for v in variants)
    assert variants[0]["params"]["chunk_size"] == 100
    assert variants[-1]["params"]["chunk_size"] == 400
    print(f"PASS: test_generate_config_variants ({len(variants)} variants)")


def test_generate_prompt_variants():
    """Prompt variants should match PROMPT_VARIANTS."""
    agent = SelfHealingAgent()
    variants = agent._generate_variants("prompt", "prompt_failure")
    assert len(variants) == len(PROMPT_VARIANTS)
    assert all(v["variant_type"] == "prompt" for v in variants)
    ids = {v["variant_id"] for v in variants}
    assert "citation_enforced" in ids
    assert "evidence_first" in ids
    assert "context_only_strict" in ids
    assert "direct_answer" in ids
    print(f"PASS: test_generate_prompt_variants ({len(variants)} variants)")


def test_composite_score():
    """Composite = 0.5 * context_precision + 0.5 * groundedness."""
    agent = SelfHealingAgent()
    score = agent._composite_score({"contextual_relevancy": 80, "faithfulness": 60})
    assert score == 70.0, f"Expected 70.0, got {score}"

    # Fallback: average when no key metrics
    score2 = agent._composite_score({"answer_relevancy": 90, "toxicity": 80})
    assert score2 == 85.0, f"Expected 85.0, got {score2}"

    # Empty
    score3 = agent._composite_score({})
    assert score3 == 0.0
    print("PASS: test_composite_score")


def test_manual_review_recommendation():
    """Non-auto-healable root causes → manual review."""
    agent = SelfHealingAgent()
    diag = {
        "root_cause": "safety_failure",
        "category": "Safety",
        "evidence": ["Toxicity score is low (15%)"],
        "recommendation": "Add safety guardrails.",
    }
    rec = agent._manual_review_recommendation(diag)
    assert rec.fix_type == "manual_review"
    assert rec.requires_manual_review
    assert rec.confidence == 0.0
    assert "safety_failure" in rec.recommendation
    print("PASS: test_manual_review_recommendation")


def test_select_best_improved():
    """Variant with higher composite score → selected as best."""
    agent = SelfHealingAgent()
    variants = [
        VariantResult("v1", "config", {"chunk_size": 100}, {"faithfulness": 60, "contextual_relevancy": 55}, 57.5, False),
        VariantResult("v2", "config", {"chunk_size": 200}, {"faithfulness": 75, "contextual_relevancy": 80}, 77.5, True),
        VariantResult("v3", "config", {"chunk_size": 300}, {"faithfulness": 90, "contextual_relevancy": 85}, 87.5, True),
    ]
    original_scores = {"faithfulness": 30, "contextual_relevancy": 25}

    rec = agent._select_best(variants, original_scores, "retrieval_failure", "config")
    assert rec.best_variant is not None
    assert rec.best_variant["chunk_size"] == 300, f"Expected chunk_size=300, got {rec.best_variant}"
    assert rec.confidence >= 0.75
    assert not rec.requires_manual_review
    assert rec.improvement is not None
    print(f"PASS: test_select_best_improved (best=chunk_size={rec.best_variant['chunk_size']}, confidence={rec.confidence})")


def test_select_best_no_improvement():
    """If nothing improves, recommend manual review."""
    agent = SelfHealingAgent()
    variants = [
        VariantResult("v1", "config", {"chunk_size": 100}, {"faithfulness": 20, "contextual_relevancy": 15}, 17.5, False),
        VariantResult("v2", "config", {"chunk_size": 200}, {"faithfulness": 25, "contextual_relevancy": 20}, 22.5, False),
    ]
    original_scores = {"faithfulness": 30, "contextual_relevancy": 25}

    rec = agent._select_best(variants, original_scores, "retrieval_failure", "config")
    assert rec.requires_manual_review
    assert rec.best_variant is None  # No improvement
    print("PASS: test_select_best_no_improvement")


def test_rechunk_context():
    """Context re-chunking with different parameters."""
    agent = SelfHealingAgent()
    context = ["This is a long document about benefits. " * 20]
    chunks = agent._rechunk_context(context, chunk_size=100, overlap=20, top_k=3)
    assert len(chunks) <= 3
    assert all(len(c) <= 100 for c in chunks)
    print(f"PASS: test_rechunk_context ({len(chunks)} chunks)")


def test_heal_retrieval_with_mock():
    """End-to-end: retrieval_failure → config optimization with mock executor/evaluator."""
    agent = SelfHealingAgent()

    rca_diagnoses = [
        {
            "root_cause": "retrieval_failure",
            "category": "Retrieval",
            "confidence": 0.6,
            "evidence": ["faithfulness low", "context_relevancy low"],
            "recommendation": "Adjust chunking",
            "failed_metrics": ["faithfulness", "contextual_relevancy"],
        }
    ]

    # Score sequence: each variant gets progressively better scores
    mock_evaluator = MockEvaluator(score_sequence=[
        {"faithfulness": 40, "contextual_relevancy": 35},   # config_1
        {"faithfulness": 55, "contextual_relevancy": 60},   # config_2
        {"faithfulness": 85, "contextual_relevancy": 82},   # config_3 ← best
        {"faithfulness": 70, "contextual_relevancy": 75},   # config_4
    ])

    result = asyncio.run(agent.heal(
        rca_diagnoses=rca_diagnoses,
        original_scores={"faithfulness": 30, "contextual_relevancy": 25},
        endpoint="http://localhost:8005/ask",
        input_text="What is PTO policy?",
        expected="15 days",
        context=["PTO policy allows 15 days off per year."],
        metrics=["faithfulness", "contextual_relevancy"],
        executor=MockExecutor(),
        evaluator=mock_evaluator,
    ))

    assert result.healed, f"Expected healed=True but got {result.summary}"
    assert result.total_variants_tested == 4
    assert len(result.recommendations) == 1
    rec = result.recommendations[0]
    assert rec.fix_type == "config_optimization"
    assert rec.best_variant is not None
    assert rec.best_variant["chunk_size"] == 300  # config_3
    assert rec.confidence >= 0.75
    print(f"PASS: test_heal_retrieval_with_mock (best={rec.best_variant}, conf={rec.confidence})")


def test_heal_prompt_with_mock():
    """End-to-end: prompt_failure → prompt optimization with mock."""
    agent = SelfHealingAgent()

    rca_diagnoses = [
        {
            "root_cause": "prompt_failure",
            "category": "Prompt",
            "confidence": 0.85,
            "evidence": ["faithfulness low but context OK"],
            "recommendation": "Improve system prompt",
            "failed_metrics": ["faithfulness"],
        }
    ]

    mock_evaluator = MockEvaluator(score_sequence=[
        {"faithfulness": 50, "contextual_relevancy": 90},   # citation_enforced
        {"faithfulness": 80, "contextual_relevancy": 88},   # evidence_first ← best
        {"faithfulness": 65, "contextual_relevancy": 85},   # context_only_strict
        {"faithfulness": 45, "contextual_relevancy": 92},   # direct_answer
    ])

    mock_executor = MockExecutor()

    result = asyncio.run(agent.heal(
        rca_diagnoses=rca_diagnoses,
        original_scores={"faithfulness": 40, "contextual_relevancy": 92},
        endpoint="http://localhost:8005/ask",
        input_text="Explain parental leave",
        expected="12 weeks",
        context=["Parental leave: 12 weeks paid."],
        metrics=["faithfulness", "contextual_relevancy"],
        executor=mock_executor,
        evaluator=mock_evaluator,
    ))

    assert result.healed
    assert result.total_variants_tested == 4
    rec = result.recommendations[0]
    assert rec.fix_type == "prompt_optimization"
    assert rec.best_variant is not None
    # Verify executor received modified inputs (with prompt suffix)
    assert len(mock_executor.calls) == 4
    # At least one call should have a system instruction appended
    any_modified = any("[System instruction:" in c["input"] for c in mock_executor.calls)
    assert any_modified, "Expected prompt variants to modify input text"
    print(f"PASS: test_heal_prompt_with_mock (best={rec.best_variant.get('id', '?')}, conf={rec.confidence})")


def test_heal_manual_review():
    """Planning/safety failures → manual review, no variants tested."""
    agent = SelfHealingAgent()

    rca_diagnoses = [
        {
            "root_cause": "planning_failure",
            "category": "Planning",
            "confidence": 0.7,
            "evidence": ["Agent reasoning weak"],
            "recommendation": "Fix planner logic",
            "failed_metrics": ["agent_reasoning"],
        },
        {
            "root_cause": "safety_failure",
            "category": "Safety",
            "confidence": 0.9,
            "evidence": ["Toxicity low"],
            "recommendation": "Add guardrails",
            "failed_metrics": ["toxicity"],
        },
    ]

    result = asyncio.run(agent.heal(
        rca_diagnoses=rca_diagnoses,
        original_scores={"agent_reasoning": 30, "toxicity": 15},
        endpoint="http://localhost:8005/ask",
        input_text="test",
        executor=MockExecutor(),
        evaluator=MockEvaluator(),
    ))

    assert not result.healed
    assert result.total_variants_tested == 0
    assert len(result.recommendations) == 2
    assert all(r.requires_manual_review for r in result.recommendations)
    print(f"PASS: test_heal_manual_review ({len(result.recommendations)} manual recommendations)")


def test_heal_mixed_causes():
    """Mix of auto-healable + manual → partial healing."""
    agent = SelfHealingAgent()

    rca_diagnoses = [
        {
            "root_cause": "retrieval_failure",
            "category": "Retrieval",
            "confidence": 0.6,
            "evidence": ["faithfulness low"],
            "recommendation": "Adjust chunking",
            "failed_metrics": ["faithfulness", "contextual_relevancy"],
        },
        {
            "root_cause": "safety_failure",
            "category": "Safety",
            "confidence": 0.9,
            "evidence": ["Toxicity low"],
            "recommendation": "Add guardrails",
            "failed_metrics": ["toxicity"],
        },
    ]

    mock_evaluator = MockEvaluator(score_sequence=[
        {"faithfulness": 60, "contextual_relevancy": 65},
        {"faithfulness": 75, "contextual_relevancy": 80},
        {"faithfulness": 90, "contextual_relevancy": 88},
        {"faithfulness": 82, "contextual_relevancy": 78},
    ])

    result = asyncio.run(agent.heal(
        rca_diagnoses=rca_diagnoses,
        original_scores={"faithfulness": 30, "contextual_relevancy": 25, "toxicity": 15},
        endpoint="http://localhost:8005/ask",
        input_text="test",
        context=["Some context here."],
        executor=MockExecutor(),
        evaluator=mock_evaluator,
    ))

    assert result.healed  # retrieval was fixed
    assert result.total_variants_tested == 4  # only config variants
    # One auto-healed + one manual
    auto = [r for r in result.recommendations if not r.requires_manual_review]
    manual = [r for r in result.recommendations if r.requires_manual_review]
    assert len(auto) == 1
    assert len(manual) == 1
    print(f"PASS: test_heal_mixed_causes (auto={len(auto)}, manual={len(manual)})")


def test_to_dict_serialization():
    """HealingResult.to_dict() is JSON-serializable."""
    agent = SelfHealingAgent()

    result = asyncio.run(agent.heal(
        rca_diagnoses=[
            {"root_cause": "planning_failure", "category": "Planning",
             "confidence": 0.5, "evidence": ["test"], "recommendation": "fix",
             "failed_metrics": ["agent_reasoning"]}
        ],
        original_scores={"agent_reasoning": 30},
        endpoint="http://localhost:8005/ask",
        input_text="test",
    ))

    d = result.to_dict()
    assert isinstance(d, dict)
    assert "healed" in d
    assert "recommendations" in d
    assert "summary" in d
    assert "total_variants_tested" in d
    assert isinstance(d["recommendations"], list)
    if d["recommendations"]:
        rec = d["recommendations"][0]
        assert "fix_type" in rec
        assert "root_cause" in rec
        assert "confidence" in rec
    print("PASS: test_to_dict_serialization")


if __name__ == "__main__":
    tests = [
        test_classify_fix_path,
        test_generate_config_variants,
        test_generate_prompt_variants,
        test_composite_score,
        test_manual_review_recommendation,
        test_select_best_improved,
        test_select_best_no_improvement,
        test_rechunk_context,
        test_heal_retrieval_with_mock,
        test_heal_prompt_with_mock,
        test_heal_manual_review,
        test_heal_mixed_causes,
        test_to_dict_serialization,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{passed+failed} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED ✓")
    else:
        print(f"{failed} TEST(S) FAILED ✗")
