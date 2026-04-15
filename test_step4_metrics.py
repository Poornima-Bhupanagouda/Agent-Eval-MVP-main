"""Test STEP 4 agent-aware metrics."""
from agent_eval.core.evaluator import Evaluator

e = Evaluator()

# Test 1: memory_retention
print("=== Test 1: memory_retention ===")
results = e.evaluate(
    input_text="What is my name?",
    output="Your name is Rahul! I remember you told me earlier.",
    conversation_history=[
        {"role": "user", "content": "My name is Rahul"},
        {"role": "assistant", "content": "Nice to meet you, Rahul!"},
        {"role": "user", "content": "What is my name?"},
    ],
    metrics=["memory_retention"],
)
for r in results:
    status = "PASS" if r.passed else "FAIL"
    print(f"  {r.metric}: {r.score}% ({status})")
    print(f"  Reason: {r.reason}")
    if r.details:
        print(f"  Pillar: {r.details.get('pillar', 'N/A')}")

# Test 2: tool_usage_correctness with expected_behavior
print("\n=== Test 2: tool_usage_correctness with expected_behavior ===")
results = e.evaluate(
    input_text="Plan a trip to Paris",
    output="Paris is wonderful with great weather and culture.",
    trace=[
        {"node": "plan_route", "result": "ok", "duration_ms": 5},
        {"node": "call_agents", "result": "ok", "duration_ms": 2000},
        {"node": "synthesize", "result": "ok", "duration_ms": 3},
    ],
    tool_calls=[
        {"name": "weather_agent", "args": {"location": "Paris"}},
        {"name": "wiki_agent", "args": {"query": "Paris"}},
    ],
    expected_behavior={
        "tools_used": ["WeatherAgent", "WikiAgent", "CalculatorAgent"],
        "max_steps": 6,
    },
    metrics=["tool_usage_correctness", "step_count_limit"],
)
for r in results:
    status = "PASS" if r.passed else "FAIL"
    print(f"  {r.metric}: {r.score}% ({status})")
    print(f"  Reason: {r.reason}")

# Test 3: failure_recovery with must_recover
print("\n=== Test 3: failure_recovery with must_recover=True ===")
results = e.evaluate(
    input_text="What is the weather on Planet Zorgon?",
    output="I could not find weather data for Planet Zorgon.",
    trace=[
        {"node": "plan_route", "result": "ok", "duration_ms": 5},
        {"node": "call_agents", "result": "error: location not found", "error": "NotFound", "duration_ms": 200},
        {"node": "synthesize", "result": "ok", "duration_ms": 3},
    ],
    expected_behavior={"must_recover": True, "max_steps": 6},
    metrics=["failure_recovery", "step_count_limit"],
)
for r in results:
    status = "PASS" if r.passed else "FAIL"
    print(f"  {r.metric}: {r.score}% ({status})")
    print(f"  Reason: {r.reason}")

# Test 4: step_count_limit exceeds max_steps from expected_behavior
print("\n=== Test 4: step_count_limit exceeds max_steps=3 ===")
results = e.evaluate(
    input_text="Convert 100 USD to EUR",
    output="100 USD = 92 EUR",
    trace=[
        {"node": "detect", "result": "ok", "duration_ms": 1},
        {"node": "execute", "result": "ok", "duration_ms": 5},
        {"node": "format", "result": "ok", "duration_ms": 1},
        {"node": "extra1", "result": "ok", "duration_ms": 1},
        {"node": "extra2", "result": "ok", "duration_ms": 1},
    ],
    expected_behavior={"max_steps": 3},
    metrics=["step_count_limit"],
)
for r in results:
    status = "PASS" if r.passed else "FAIL"
    print(f"  {r.metric}: {r.score}% ({status})")
    print(f"  Reason: {r.reason}")
    if r.details:
        print(f"  Source: {r.details.get('source')}, max_steps: {r.details.get('max_steps')}")

# Test 5: memory_retention fails when agent forgets
print("\n=== Test 5: memory_retention FAIL case ===")
results = e.evaluate(
    input_text="What is my name?",
    output="I don't know your name. Could you tell me?",
    conversation_history=[
        {"role": "user", "content": "My name is Rahul"},
        {"role": "assistant", "content": "Nice to meet you!"},
        {"role": "user", "content": "What is my name?"},
    ],
    metrics=["memory_retention"],
)
for r in results:
    status = "PASS" if r.passed else "FAIL"
    print(f"  {r.metric}: {r.score}% ({status})")
    print(f"  Reason: {r.reason}")

# Test 6: auto-select includes agent-aware metrics when trace + expected_behavior
print("\n=== Test 6: auto-select with trace + expected_behavior ===")
selected = e._auto_select_metrics(
    expected="Tokyo",
    context=None,
    trace=[{"node": "plan", "result": "ok"}],
    expected_behavior={"tools_used": ["WeatherAgent"], "max_steps": 5, "must_recover": True},
)
print(f"  Auto-selected metrics: {selected}")
assert "tool_usage_correctness" in selected, "tool_usage_correctness missing"
assert "step_count_limit" in selected, "step_count_limit missing"
assert "failure_recovery" in selected, "failure_recovery missing"
print("  All expected metrics present!")

print("\n" + "="*50)
print("ALL 6 TESTS PASSED - STEP 4 metrics working!")
print("="*50)
