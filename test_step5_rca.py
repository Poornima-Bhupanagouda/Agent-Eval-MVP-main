"""
STEP 5 — Root Cause Analysis (RCA) Agent Unit Tests.

Tests the RCA decision tree against known failure patterns
to verify it produces correct diagnoses.
"""

import sys
sys.path.insert(0, ".")

from agent_eval.core.rca import RCAAgent, RCAResult, RCADiagnosis


def test_all_pass_no_rca():
    """When all metrics pass, RCA should report no failures."""
    agent = RCAAgent()
    result = agent.analyze(evaluations=[
        {"metric": "faithfulness", "score": 95, "passed": True, "reason": "Good"},
        {"metric": "answer_relevancy", "score": 88, "passed": True, "reason": "Relevant"},
        {"metric": "tool_usage_correctness", "score": 100, "passed": True, "reason": "All tools correct"},
    ])
    assert not result.has_failures, f"Expected no failures but got: {result.summary}"
    assert len(result.diagnoses) == 0
    assert result.metrics_analyzed == 3
    print("PASS: test_all_pass_no_rca")


def test_retrieval_failure():
    """Low faithfulness + low context_relevancy → retrieval failure."""
    agent = RCAAgent()
    result = agent.analyze(evaluations=[
        {"metric": "faithfulness", "score": 30, "passed": False, "reason": "Not grounded"},
        {"metric": "contextual_relevancy", "score": 25, "passed": False, "reason": "Irrelevant chunks"},
        {"metric": "answer_relevancy", "score": 85, "passed": True, "reason": "OK"},
    ])
    assert result.has_failures
    assert any(d.root_cause == "retrieval_failure" for d in result.diagnoses), \
        f"Expected retrieval_failure, got: {[d.root_cause for d in result.diagnoses]}"
    diag = [d for d in result.diagnoses if d.root_cause == "retrieval_failure"][0]
    assert "faithfulness" in diag.failed_metrics
    assert "contextual_relevancy" in diag.failed_metrics
    assert diag.confidence >= 0.5
    print(f"PASS: test_retrieval_failure (confidence={diag.confidence})")


def test_prompt_failure():
    """Low faithfulness + OK context → prompt problem."""
    agent = RCAAgent()
    result = agent.analyze(evaluations=[
        {"metric": "faithfulness", "score": 40, "passed": False, "reason": "Hallucinating"},
        {"metric": "contextual_relevancy", "score": 92, "passed": True, "reason": "Context is relevant"},
        {"metric": "answer_relevancy", "score": 35, "passed": False, "reason": "Off topic"},
    ])
    assert result.has_failures
    assert any(d.root_cause == "prompt_failure" for d in result.diagnoses), \
        f"Expected prompt_failure, got: {[d.root_cause for d in result.diagnoses]}"
    diag = [d for d in result.diagnoses if d.root_cause == "prompt_failure"][0]
    assert diag.confidence >= 0.7
    print(f"PASS: test_prompt_failure (confidence={diag.confidence})")


def test_planning_failure_wrong_tool():
    """Low tool_usage_correctness → wrong tool selected."""
    agent = RCAAgent()
    result = agent.analyze(evaluations=[
        {"metric": "tool_usage_correctness", "score": 20, "passed": False, "reason": "Wrong tool"},
        {"metric": "tool_order_correctness", "score": 50, "passed": False, "reason": "Wrong order"},
        {"metric": "answer_relevancy", "score": 90, "passed": True, "reason": "OK"},
    ])
    assert result.has_failures
    planning_diags = [d for d in result.diagnoses if d.category == "Planning"]
    assert len(planning_diags) > 0, f"Expected Planning diagnosis, got: {[d.category for d in result.diagnoses]}"
    diag = planning_diags[0]
    assert diag.root_cause == "wrong_tool_selected"
    assert "tool_usage_correctness" in diag.failed_metrics
    print(f"PASS: test_planning_failure_wrong_tool (root_cause={diag.root_cause})")


def test_performance_failure():
    """High latency + step count exceeded."""
    agent = RCAAgent()
    result = agent.analyze(
        evaluations=[
            {"metric": "step_latency", "score": 30, "passed": False, "reason": "Slow step"},
            {"metric": "step_count_limit", "score": 40, "passed": False, "reason": "Too many steps"},
            {"metric": "answer_relevancy", "score": 95, "passed": True, "reason": "Good"},
        ],
        latency_ms=15000,
    )
    assert result.has_failures
    perf_diags = [d for d in result.diagnoses if d.category == "Performance"]
    assert len(perf_diags) > 0, f"Expected Performance diagnosis, got: {[d.category for d in result.diagnoses]}"
    diag = perf_diags[0]
    assert diag.root_cause == "performance_failure"
    print(f"PASS: test_performance_failure (evidence count={len(diag.evidence)})")


def test_memory_failure():
    """Low memory_retention → memory problem."""
    agent = RCAAgent()
    result = agent.analyze(evaluations=[
        {"metric": "memory_retention", "score": 25, "passed": False, "reason": "Forgot name"},
        {"metric": "context_retention", "score": 40, "passed": False, "reason": "Lost earlier turns"},
        {"metric": "answer_relevancy", "score": 80, "passed": True, "reason": "OK"},
    ])
    assert result.has_failures
    mem_diags = [d for d in result.diagnoses if d.category == "Memory"]
    assert len(mem_diags) > 0
    diag = mem_diags[0]
    assert diag.root_cause == "memory_failure"
    assert "memory_retention" in diag.failed_metrics
    print(f"PASS: test_memory_failure (confidence={diag.confidence})")


def test_safety_failure():
    """Low toxicity → safety issue."""
    agent = RCAAgent()
    result = agent.analyze(evaluations=[
        {"metric": "toxicity", "score": 15, "passed": False, "reason": "Toxic content"},
        {"metric": "bias", "score": 30, "passed": False, "reason": "Biased response"},
    ])
    assert result.has_failures
    safety_diags = [d for d in result.diagnoses if d.category == "Safety"]
    assert len(safety_diags) > 0
    diag = safety_diags[0]
    assert diag.root_cause == "safety_failure"
    assert "CRITICAL" in diag.recommendation
    print(f"PASS: test_safety_failure (confidence={diag.confidence})")


def test_robustness_failure():
    """Low failure_recovery → robustness problem."""
    agent = RCAAgent()
    result = agent.analyze(
        evaluations=[
            {"metric": "failure_recovery", "score": 20, "passed": False, "reason": "No fallback"},
            {"metric": "node_success_rate", "score": 50, "passed": False, "reason": "Nodes failing"},
        ],
        trace=[
            {"node": "planner", "duration_ms": 100, "result": "ok"},
            {"node": "executor", "duration_ms": 50, "error": "ConnectionError"},
        ],
    )
    assert result.has_failures
    rob_diags = [d for d in result.diagnoses if d.category == "Robustness"]
    assert len(rob_diags) > 0
    diag = rob_diags[0]
    assert diag.root_cause == "robustness_failure"
    # Should include trace error evidence
    assert any("Trace errors" in e for e in diag.evidence)
    print(f"PASS: test_robustness_failure (evidence={diag.evidence})")


def test_multiple_root_causes():
    """Multiple simultaneous failures → multiple diagnoses."""
    agent = RCAAgent()
    result = agent.analyze(
        evaluations=[
            {"metric": "faithfulness", "score": 30, "passed": False, "reason": "Not grounded"},
            {"metric": "contextual_relevancy", "score": 25, "passed": False, "reason": "Bad chunks"},
            {"metric": "tool_usage_correctness", "score": 40, "passed": False, "reason": "Wrong tool"},
            {"metric": "memory_retention", "score": 20, "passed": False, "reason": "Forgot name"},
        ],
    )
    assert result.has_failures
    categories = {d.category for d in result.diagnoses}
    assert "Retrieval" in categories, f"Missing Retrieval diagnosis: {categories}"
    assert "Planning" in categories, f"Missing Planning diagnosis: {categories}"
    assert "Memory" in categories, f"Missing Memory diagnosis: {categories}"
    # Diagnoses sorted by confidence (highest first)
    for i in range(len(result.diagnoses) - 1):
        assert result.diagnoses[i].confidence >= result.diagnoses[i+1].confidence
    print(f"PASS: test_multiple_root_causes ({len(result.diagnoses)} diagnoses, categories={categories})")


def test_to_dict_serialization():
    """RCAResult.to_dict() produces clean JSON-serializable output."""
    agent = RCAAgent()
    result = agent.analyze(evaluations=[
        {"metric": "faithfulness", "score": 30, "passed": False, "reason": "Bad"},
    ])
    d = result.to_dict()
    assert isinstance(d, dict)
    assert "has_failures" in d
    assert "diagnoses" in d
    assert "summary" in d
    assert isinstance(d["diagnoses"], list)
    if d["diagnoses"]:
        diag = d["diagnoses"][0]
        assert "root_cause" in diag
        assert "confidence" in diag
        assert "evidence" in diag
        assert "recommendation" in diag
    print(f"PASS: test_to_dict_serialization")


def test_summary_output():
    """Summary string is human-readable."""
    agent = RCAAgent()
    result = agent.analyze(evaluations=[
        {"metric": "tool_usage_correctness", "score": 20, "passed": False, "reason": "Wrong"},
        {"metric": "faithfulness", "score": 30, "passed": False, "reason": "Not grounded"},
        {"metric": "contextual_relevancy", "score": 25, "passed": False, "reason": "Bad chunks"},
    ])
    assert result.summary
    assert "Primary root cause:" in result.summary
    assert "Contributing factors:" in result.summary
    print(f"PASS: test_summary_output → {result.summary[:80]}...")


if __name__ == "__main__":
    tests = [
        test_all_pass_no_rca,
        test_retrieval_failure,
        test_prompt_failure,
        test_planning_failure_wrong_tool,
        test_performance_failure,
        test_memory_failure,
        test_safety_failure,
        test_robustness_failure,
        test_multiple_root_causes,
        test_to_dict_serialization,
        test_summary_output,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL: {t.__name__} — {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{passed+failed} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED ✓")
    else:
        print(f"{failed} TEST(S) FAILED ✗")
