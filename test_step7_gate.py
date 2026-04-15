"""
STEP 7 — Deployment Gate Unit Tests.

Tests the GO / NO-GO decision logic, composite scoring,
hard-block safety checks, and edge cases.
"""

import sys
sys.path.insert(0, ".")

from agent_eval.core.deployment_gate import (
    DeploymentGate, GateVerdict, deployment_gate,
    WEIGHTS, DEFAULT_THRESHOLD, LATENCY_FAST_MS, LATENCY_FACTOR_SLOW,
)


def make_evals(**kwargs):
    """Helper to make evaluation dicts from metric=score pairs."""
    return [
        {"metric": m, "score": s, "passed": s >= 70, "reason": "test"}
        for m, s in kwargs.items()
    ]


def test_go_all_pass():
    """All metrics high + fast latency → GO."""
    gate = DeploymentGate()
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=90, answer_relevancy=85, contextual_relevancy=88),
        latency_ms=2000,
    )
    assert verdict.decision == "GO", f"Expected GO, got {verdict.decision} (score={verdict.final_score})"
    assert verdict.final_score >= 0.70
    assert "latency" in verdict.passed_dimensions
    assert len(verdict.failed_dimensions) == 0
    print(f"PASS: test_go_all_pass (score={verdict.final_score:.4f})")


def test_no_go_low_scores():
    """All metrics low → NO-GO."""
    gate = DeploymentGate()
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=30, answer_relevancy=25, contextual_relevancy=20),
        latency_ms=2000,
    )
    assert verdict.decision == "NO-GO", f"Expected NO-GO, got {verdict.decision}"
    assert verdict.final_score < 0.70
    assert "faithfulness" in verdict.failed_dimensions
    assert "answer_relevancy" in verdict.failed_dimensions
    assert "groundedness" in verdict.failed_dimensions
    print(f"PASS: test_no_go_low_scores (score={verdict.final_score:.4f})")


def test_composite_formula():
    """Verify exact composite score calculation."""
    gate = DeploymentGate()
    # faithfulness=80, answer_relevancy=70, groundedness=60, latency≤5s
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=80, answer_relevancy=70, contextual_relevancy=60),
        latency_ms=3000,
    )
    # Expected: 0.40*0.80 + 0.30*0.70 + 0.20*0.60 + 0.10*1.0
    #         = 0.32     + 0.21     + 0.12     + 0.10
    #         = 0.75
    expected = 0.32 + 0.21 + 0.12 + 0.10
    assert abs(verdict.final_score - expected) < 0.001, \
        f"Expected {expected}, got {verdict.final_score}"
    assert verdict.decision == "GO"
    print(f"PASS: test_composite_formula (score={verdict.final_score:.4f} == {expected})")


def test_latency_factor_slow():
    """Latency > 5s → factor 0.3 instead of 1.0."""
    gate = DeploymentGate()
    # Same scores, but slow latency
    verdict_fast = gate.evaluate(
        evaluations=make_evals(faithfulness=80, answer_relevancy=70, contextual_relevancy=60),
        latency_ms=3000,
    )
    verdict_slow = gate.evaluate(
        evaluations=make_evals(faithfulness=80, answer_relevancy=70, contextual_relevancy=60),
        latency_ms=8000,
    )
    assert verdict_slow.latency_factor == LATENCY_FACTOR_SLOW
    assert verdict_fast.latency_factor == 1.0
    # Slow should score 0.07 less (0.10 * (1.0 - 0.3))
    diff = verdict_fast.final_score - verdict_slow.final_score
    assert abs(diff - 0.07) < 0.001, f"Expected 0.07 diff, got {diff}"
    assert "latency" in verdict_slow.failed_dimensions
    print(f"PASS: test_latency_factor_slow (fast={verdict_fast.final_score:.4f}, slow={verdict_slow.final_score:.4f})")


def test_hard_block_toxicity():
    """Toxicity failure → NO-GO regardless of composite score."""
    gate = DeploymentGate()
    verdict = gate.evaluate(
        evaluations=make_evals(
            faithfulness=95, answer_relevancy=95, contextual_relevancy=95,
            toxicity=20,
        ),
        latency_ms=1000,
    )
    assert verdict.decision == "NO-GO", f"Expected NO-GO due to toxicity, got {verdict.decision}"
    assert "toxicity" in verdict.failed_dimensions
    assert "BLOCKED" in verdict.recommended_action
    print(f"PASS: test_hard_block_toxicity (score={verdict.final_score:.4f}, decision={verdict.decision})")


def test_hard_block_bias():
    """Bias failure → NO-GO regardless of composite score."""
    gate = DeploymentGate()
    verdict = gate.evaluate(
        evaluations=make_evals(
            faithfulness=90, answer_relevancy=90, contextual_relevancy=90,
            bias=30,
        ),
        latency_ms=1000,
    )
    assert verdict.decision == "NO-GO"
    assert "bias" in verdict.failed_dimensions
    assert "BLOCKED" in verdict.recommended_action
    print(f"PASS: test_hard_block_bias (decision={verdict.decision})")


def test_borderline_go():
    """Score exactly at threshold → GO."""
    gate = DeploymentGate()
    # Need final_score = 0.70 exactly
    # 0.40*F + 0.30*R + 0.20*G + 0.10*1.0 = 0.70
    # 0.40*F + 0.30*R + 0.20*G = 0.60
    # If all same: 0.90*X = 0.60 → X = 0.6667 → score = 66.67
    # Let's use faithfulness=70, answer_relevancy=70, groundedness=55
    # 0.40*0.70 + 0.30*0.70 + 0.20*0.55 + 0.10*1.0
    # = 0.28 + 0.21 + 0.11 + 0.10 = 0.70
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=70, answer_relevancy=70, contextual_relevancy=55),
        latency_ms=2000,
    )
    assert abs(verdict.final_score - 0.70) < 0.001
    assert verdict.decision == "GO"
    print(f"PASS: test_borderline_go (score={verdict.final_score:.4f})")


def test_borderline_no_go():
    """Score just below threshold → NO-GO."""
    gate = DeploymentGate()
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=69, answer_relevancy=70, contextual_relevancy=55),
        latency_ms=2000,
    )
    assert verdict.final_score < 0.70
    assert verdict.decision == "NO-GO"
    print(f"PASS: test_borderline_no_go (score={verdict.final_score:.4f})")


def test_custom_threshold():
    """Custom threshold overrides default 0.70."""
    gate = DeploymentGate()
    evals = make_evals(faithfulness=60, answer_relevancy=55, contextual_relevancy=50)

    # Default threshold → NO-GO
    v1 = gate.evaluate(evaluations=evals, latency_ms=2000)
    assert v1.decision == "NO-GO"

    # Lower threshold → GO
    v2 = gate.evaluate(evaluations=evals, latency_ms=2000, threshold=0.50)
    assert v2.decision == "GO"
    assert v2.threshold == 0.50
    print(f"PASS: test_custom_threshold (default={v1.decision}, low={v2.decision})")


def test_missing_metrics_graceful():
    """Gate works even when some metrics are missing (fallbacks apply)."""
    gate = DeploymentGate()
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=90),
        latency_ms=2000,
    )
    # faithfulness=90, answer_relevancy=0 (missing), groundedness falls back to faithfulness=90
    # 0.40*0.90 + 0.30*0.00 + 0.20*0.90 + 0.10*1.0
    # = 0.36 + 0.00 + 0.18 + 0.10 = 0.64
    assert verdict.final_score < 0.70
    assert verdict.decision == "NO-GO"
    assert "answer_relevancy" in verdict.failed_dimensions
    print(f"PASS: test_missing_metrics_graceful (score={verdict.final_score:.4f})")


def test_healing_context_in_recommendation():
    """When healing was applied, recommendation mentions it."""
    gate = DeploymentGate()
    healing_result = {
        "healed": True,
        "recommendations": [
            {
                "fix_type": "config_optimization",
                "improvement": {"faithfulness": "+25.0", "contextual_relevancy": "+20.0"},
            }
        ],
    }
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=50, answer_relevancy=55, contextual_relevancy=45),
        latency_ms=2000,
        healing_result=healing_result,
    )
    assert verdict.decision == "NO-GO"
    assert verdict.healing_applied
    assert verdict.healing_improvement is not None
    assert "Self-healing" in verdict.recommended_action or "improvements" in verdict.recommended_action
    print(f"PASS: test_healing_context_in_recommendation")


def test_score_breakdown():
    """Score breakdown shows individual weighted contributions."""
    gate = DeploymentGate()
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=80, answer_relevancy=70, contextual_relevancy=60),
        latency_ms=2000,
    )
    bd = verdict.score_breakdown
    assert "faithfulness" in bd
    assert "answer_relevancy" in bd
    assert "groundedness" in bd
    assert "latency_factor" in bd
    assert abs(bd["faithfulness"] - 0.32) < 0.001
    assert abs(bd["answer_relevancy"] - 0.21) < 0.001
    assert abs(bd["groundedness"] - 0.12) < 0.001
    assert abs(bd["latency_factor"] - 0.10) < 0.001
    print(f"PASS: test_score_breakdown ({bd})")


def test_to_dict_serialization():
    """GateVerdict.to_dict() is JSON-serializable."""
    gate = DeploymentGate()
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=80, answer_relevancy=75, contextual_relevancy=70),
        latency_ms=2000,
    )
    d = verdict.to_dict()
    assert isinstance(d, dict)
    assert d["decision"] in ("GO", "NO-GO")
    assert "final_score" in d
    assert "threshold" in d
    assert "score_breakdown" in d
    assert "failed_dimensions" in d
    assert "recommended_action" in d
    assert "created_at" in d
    print(f"PASS: test_to_dict_serialization")


def test_go_with_partial_failures():
    """Composite can be GO even if one dimension fails (weighted formula)."""
    gate = DeploymentGate()
    # faithfulness=95, answer_relevancy=90, groundedness=40 (fails)
    # 0.40*0.95 + 0.30*0.90 + 0.20*0.40 + 0.10*1.0
    # = 0.38 + 0.27 + 0.08 + 0.10 = 0.83
    verdict = gate.evaluate(
        evaluations=make_evals(faithfulness=95, answer_relevancy=90, contextual_relevancy=40),
        latency_ms=2000,
    )
    assert verdict.decision == "GO"
    assert "groundedness" in verdict.failed_dimensions
    assert "monitor" in verdict.recommended_action.lower() or "Note" in verdict.recommended_action
    print(f"PASS: test_go_with_partial_failures (score={verdict.final_score:.4f}, failed={verdict.failed_dimensions})")


if __name__ == "__main__":
    tests = [
        test_go_all_pass,
        test_no_go_low_scores,
        test_composite_formula,
        test_latency_factor_slow,
        test_hard_block_toxicity,
        test_hard_block_bias,
        test_borderline_go,
        test_borderline_no_go,
        test_custom_threshold,
        test_missing_metrics_graceful,
        test_healing_context_in_recommendation,
        test_score_breakdown,
        test_to_dict_serialization,
        test_go_with_partial_failures,
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
