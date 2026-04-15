"""Test: orchestrator eval with auto-selected metrics (no manual expected_tool_calls)."""
import requests

payload = {
    "endpoint": "http://127.0.0.1:8010/chat",
    "input": "Plan a 3-day trip to Paris with budget tips",
    "expected": "weather forecast, tourist attractions, country info, currency",
    "agent_type": "orchestrator",
    # NO expected_tool_calls — should be auto-built from actual calls
    # NO metrics — should be auto-selected
}

print("Testing orchestrator with auto-selection (no manual tool calls)...")
r = requests.post("http://localhost:8888/api/test", json=payload, timeout=180)
d = r.json()
print(f"Score: {d['score']}%  Pass: {d['passed']}")
print(f"Trace: {d.get('trace') is not None}")
print(f"Tool calls: {d.get('tool_calls') is not None}")
print(f"Metrics run: {len(d.get('evaluations', []))}")
for ev in d.get("evaluations", []):
    s = "PASS" if ev["passed"] else "FAIL"
    print(f"  {ev['metric']:25s} {ev['score']:>5.0f}%  {s}")
print(f"\nOutput: {d['output'][:150]}...")

# Also write to file for reliable capture
with open("test_autoselect_out.txt", "w") as f:
    f.write(f"Score: {d['score']}%  Pass: {d['passed']}\n")
    f.write(f"Metrics: {len(d.get('evaluations', []))}\n")
    for ev in d.get("evaluations", []):
        s = "PASS" if ev["passed"] else "FAIL"
        f.write(f"  {ev['metric']:25s} {ev['score']:>5.0f}%  {s}\n")
print("Results also saved to test_autoselect_out.txt")
