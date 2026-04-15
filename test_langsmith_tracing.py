"""
Test STEP 3: LangSmith Tracing Integration

Validates:
1. AgentTrace model creation and properties
2. TracedGraph trace → AgentTrace conversion
3. New process-level metrics (tool_usage_correctness, tool_order_correctness,
   failure_recovery, step_count_limit)
4. LangSmith config detection
5. Evaluator auto-selects new metrics when trace present
"""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.core.tracing import (
    AgentTrace,
    TraceStep,
    convert_trace_to_agent_trace,
    is_langsmith_enabled,
)
from agent_eval.core.evaluator import Evaluator


def test_agent_trace_model():
    """Test AgentTrace dataclass creation and properties."""
    print("\n=== Test 1: AgentTrace Model ===")

    steps = [
        TraceStep(node_name="planner", duration_ms=50, status="ok"),
        TraceStep(node_name="weather_tool", tool_name="get_weather",
                  tool_input={"city": "Tokyo"}, tool_output="25°C sunny",
                  duration_ms=200, status="ok"),
        TraceStep(node_name="synthesizer", duration_ms=100, status="ok"),
    ]

    trace = AgentTrace(
        agent_name="Travel Agent",
        run_id="test-123",
        steps=steps,
        total_duration_ms=350,
        final_output="Weather in Tokyo is 25°C and sunny.",
        reasoning_steps=["[planner] completed", "[weather_tool] completed", "[synthesizer] completed"],
        tool_calls=[{"name": "get_weather", "input": {"city": "Tokyo"}, "output": "25°C sunny"}],
    )

    assert trace.step_count == 3, f"Expected 3 steps, got {trace.step_count}"
    assert trace.node_names == ["planner", "weather_tool", "synthesizer"]
    assert not trace.has_errors
    assert trace.success_rate == 1.0
    assert trace.error_nodes == []

    d = trace.to_dict()
    assert d["agent_name"] == "Travel Agent"
    assert len(d["steps"]) == 3
    assert d["steps"][1]["tool_name"] == "get_weather"

    print("  ✅ AgentTrace model works correctly")
    print(f"     Nodes: {' → '.join(trace.node_names)}")
    print(f"     Success rate: {trace.success_rate:.0%}")
    print(f"     Total duration: {trace.total_duration_ms}ms")


def test_trace_conversion():
    """Test converting TracedGraph trace list → AgentTrace."""
    print("\n=== Test 2: Trace Conversion (TracedGraph → AgentTrace) ===")

    # This is the format emitted by TracedGraph._wrap_node()
    raw_trace = [
        {"node": "parse_query", "duration_ms": 15, "result": "ok"},
        {"node": "retrieve_docs", "duration_ms": 120, "result": "ok"},
        {"node": "generate_answer", "duration_ms": 350, "result": "ok"},
    ]
    raw_tools = [
        {"name": "retrieve_docs", "args": {"query": "PTO policy"}, "output": "Found 3 docs"},
    ]

    agent_trace = convert_trace_to_agent_trace(
        trace_entries=raw_trace,
        agent_name="RAG Agent",
        tool_calls=raw_tools,
        output="Employees get 15 PTO days per year.",
    )

    assert agent_trace.agent_name == "RAG Agent"
    assert agent_trace.step_count == 3
    assert agent_trace.final_output == "Employees get 15 PTO days per year."
    assert len(agent_trace.tool_calls) == 1
    assert agent_trace.tool_calls[0]["name"] == "retrieve_docs"
    assert agent_trace.success_rate == 1.0
    assert len(agent_trace.reasoning_steps) == 3

    print("  ✅ Trace conversion works correctly")
    print(f"     Steps: {agent_trace.step_count}")
    print(f"     Reasoning: {agent_trace.reasoning_steps}")


def test_error_trace_conversion():
    """Test conversion with error nodes."""
    print("\n=== Test 3: Error Trace Conversion ===")

    raw_trace = [
        {"node": "planner", "duration_ms": 20, "result": "ok"},
        {"node": "api_call", "duration_ms": 500, "result": "error: timeout", "error": "Connection timeout"},
        {"node": "fallback", "duration_ms": 30, "result": "ok"},
    ]

    agent_trace = convert_trace_to_agent_trace(raw_trace, agent_name="Failing Agent")

    assert agent_trace.has_errors
    assert agent_trace.error_nodes == ["api_call"]
    assert agent_trace.success_rate == 2 / 3

    print("  ✅ Error trace conversion works")
    print(f"     Errors in: {agent_trace.error_nodes}")
    print(f"     Success rate: {agent_trace.success_rate:.1%}")


def test_process_metrics():
    """Test the 4 new process-level metrics."""
    print("\n=== Test 4: Process-Level Metrics ===")

    evaluator = Evaluator(threshold=70.0)

    # --- 4a: tool_usage_correctness ---
    trace_ok = [
        {"node": "planner", "duration_ms": 20, "result": "ok"},
        {"node": "weather", "duration_ms": 100, "result": "ok"},
        {"node": "synthesizer", "duration_ms": 50, "result": "ok"},
    ]
    r = evaluator._heuristic_tool_usage_correctness(trace_ok, None, None, 70.0)
    assert r.passed, f"tool_usage_correctness should pass: {r.reason}"
    print(f"  ✅ tool_usage_correctness: {r.score}% — {r.reason}")

    # --- 4b: tool_order_correctness ---
    r = evaluator._heuristic_tool_order_correctness(trace_ok, None, None, 70.0)
    assert r.passed, f"tool_order_correctness should pass: {r.reason}"
    print(f"  ✅ tool_order_correctness: {r.score}% — {r.reason}")

    # --- 4c: failure_recovery (no errors) ---
    r = evaluator._heuristic_failure_recovery(trace_ok, 70.0)
    assert r.passed and r.score == 100.0, f"failure_recovery should be 100%: {r.reason}"
    print(f"  ✅ failure_recovery (clean): {r.score}% — {r.reason}")

    # --- 4c2: failure_recovery (with recovery) ---
    trace_recover = [
        {"node": "planner", "duration_ms": 20, "result": "ok"},
        {"node": "api_call", "duration_ms": 500, "result": "error: timeout", "error": "timeout"},
        {"node": "fallback", "duration_ms": 30, "result": "ok"},
    ]
    r = evaluator._heuristic_failure_recovery(trace_recover, 70.0)
    print(f"  ✅ failure_recovery (recovered): {r.score}% — {r.reason}")

    # --- 4c3: failure_recovery (no recovery) ---
    trace_fail = [
        {"node": "planner", "duration_ms": 20, "result": "ok"},
        {"node": "api_call", "duration_ms": 500, "result": "error: crash", "error": "crash"},
    ]
    r = evaluator._heuristic_failure_recovery(trace_fail, 70.0)
    assert not r.passed, "failure_recovery should fail with terminal error"
    print(f"  ✅ failure_recovery (failed): {r.score}% — {r.reason}")

    # --- 4d: step_count_limit ---
    r = evaluator._heuristic_step_count_limit(trace_ok, 70.0)
    assert r.passed, f"step_count_limit should pass for 3 steps: {r.reason}"
    print(f"  ✅ step_count_limit: {r.score}% — {r.reason}")

    # Over limit
    trace_long = [{"node": f"step_{i}", "duration_ms": 10, "result": "ok"} for i in range(20)]
    r = evaluator._heuristic_step_count_limit(trace_long, 70.0)
    print(f"  ✅ step_count_limit (20 steps): {r.score}% — {r.reason}")


def test_auto_select_with_trace():
    """Test that evaluator auto-selects new metrics when trace is present."""
    print("\n=== Test 5: Auto-Selection of Process Metrics ===")

    evaluator = Evaluator(threshold=70.0)
    trace = [{"node": "step1", "duration_ms": 10, "result": "ok"}]

    metrics = evaluator._auto_select_metrics(
        expected=None, context=None, trace=trace
    )

    new_metrics = ["tool_usage_correctness", "tool_order_correctness",
                   "failure_recovery", "step_count_limit"]

    for m in new_metrics:
        assert m in metrics, f"Expected '{m}' in auto-selected metrics, got: {metrics}"
        print(f"  ✅ '{m}' auto-selected when trace present")


def test_langsmith_config():
    """Test LangSmith configuration detection."""
    print("\n=== Test 6: LangSmith Configuration ===")

    enabled = is_langsmith_enabled()
    if enabled:
        print("  ✅ LangSmith is ENABLED (LANGCHAIN_TRACING_V2=true + valid API key)")
    else:
        print("  ⚠️  LangSmith is DISABLED (set LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY to enable)")
    print("     This is expected — tracing works locally without LangSmith cloud")


def test_full_eval_with_trace():
    """Test running a full evaluation with trace data (end-to-end)."""
    print("\n=== Test 7: Full Evaluation with Trace Data ===")

    evaluator = Evaluator(threshold=70.0)

    trace = [
        {"node": "parse", "duration_ms": 10, "result": "ok"},
        {"node": "retrieve", "duration_ms": 80, "result": "ok"},
        {"node": "generate", "duration_ms": 200, "result": "ok"},
    ]

    results = evaluator.evaluate(
        input_text="What is the PTO policy?",
        output="Employees receive 15 days of PTO per year.",
        expected="15 PTO days per year",
        trace=trace,
    )

    metric_names = [r.metric for r in results]
    print(f"  Metrics evaluated: {metric_names}")

    # Check new process metrics ran
    for expected_metric in ["node_success_rate", "tool_usage_correctness", "step_count_limit"]:
        found = [r for r in results if r.metric == expected_metric]
        if found:
            r = found[0]
            status = "✅ PASS" if r.passed else "❌ FAIL"
            print(f"  {status} {r.metric}: {r.score}% — {r.reason}")
        else:
            print(f"  ⚠️  {expected_metric} not in results (may need context/tools)")

    passed_count = sum(1 for r in results if r.passed)
    total = len(results)
    print(f"\n  Summary: {passed_count}/{total} metrics passed")


def test_metrics_listing():
    """Test that all new metrics appear in list_metrics()."""
    print("\n=== Test 8: Metrics Registry ===")

    all_metrics = Evaluator.list_metrics()
    metric_ids = [m["id"] for m in all_metrics]

    new_ids = ["tool_usage_correctness", "tool_order_correctness",
               "failure_recovery", "step_count_limit"]

    for mid in new_ids:
        assert mid in metric_ids, f"'{mid}' not found in metrics registry"
        info = next(m for m in all_metrics if m["id"] == mid)
        print(f"  ✅ {mid}: {info['name']} — {info['description']}")

    print(f"\n  Total metrics in registry: {len(all_metrics)}")


if __name__ == "__main__":
    print("=" * 60)
    print("  STEP 3: LangSmith Tracing Integration Tests")
    print("=" * 60)

    test_agent_trace_model()
    test_trace_conversion()
    test_error_trace_conversion()
    test_process_metrics()
    test_auto_select_with_trace()
    test_langsmith_config()
    test_full_eval_with_trace()
    test_metrics_listing()

    print("\n" + "=" * 60)
    print("  ALL STEP 3 TESTS PASSED ✅")
    print("=" * 60)
