"""Quick test to verify trace flows through the full eval pipeline."""
import requests, json

# Test 1: Orchestrator - check trace + all metrics
print("=== Orchestrator eval with all metrics ===")
payload = {
    "endpoint": "http://127.0.0.1:8010/chat",
    "input": "Plan a trip to Paris",
    "expected": "weather, attractions, currency",
    "metrics": [
        "answer_relevancy", "task_completion",
        "tool_correctness", "tool_args_accuracy", "tool_sequence",
        "node_success_rate", "step_latency", "agent_reasoning"
    ],
    "agent_type": "orchestrator",
    "expected_tool_calls": [
        {"tool": "route_to_agent", "args": {"agent": "weather_agent"}},
        {"tool": "route_to_agent", "args": {"agent": "wiki_agent"}},
        {"tool": "route_to_agent", "args": {"agent": "calculator_agent"}}
    ]
}
r = requests.post("http://localhost:8888/api/test", json=payload, timeout=180)
d = r.json()
print(f"Score: {d['score']}%  Pass: {d['passed']}")
print(f"Trace present: {d.get('trace') is not None}")
print(f"Tool calls present: {d.get('tool_calls') is not None}")
for ev in d.get("evaluations", []):
    s = "PASS" if ev["passed"] else "FAIL"
    print(f"  {ev['metric']:25s} {ev['score']:>5.0f}%  {s}")
print(f"\nOutput preview: {d['output'][:200]}")
