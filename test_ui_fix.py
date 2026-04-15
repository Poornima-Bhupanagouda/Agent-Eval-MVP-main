"""Test: simulate what the FIXED UI sends (metrics=null for auto-select)."""
import requests, json

# This is what the UI NOW sends: metrics=null lets the backend auto-select all
payload = {
    "endpoint": "http://127.0.0.1:8010/chat",
    "input": "Plan a 3-day trip to Paris with budget tips",
    "expected": None,
    "context": None,
    "metrics": None,  # New: UI sends null when user hasn't manually changed metrics
    "expected_tool_calls": None,
    "agent_type": "orchestrator",
}

print("1. Testing NEW UI behavior (metrics=null, auto-select)...")
r = requests.post("http://127.0.0.1:8888/api/test", json=payload, timeout=120)
d = r.json()
print(f"   Score: {d['score']}%  Metrics: {len(d['evaluations'])}")
for ev in d["evaluations"]:
    s = "PASS" if ev["passed"] else "FAIL"
    print(f"   {ev['metric']:25s} {ev['score']:>5.0f}%  {s}  ({ev.get('scored_by','?')})")
print(f"   trace: {'Yes' if d.get('trace') else 'No'}")
print(f"   tool_calls: {'Yes' if d.get('tool_calls') else 'No'}")

# Also test old behavior to confirm the issue
print("\n2. Testing OLD UI behavior (metrics=explicit list)...")
payload2 = {
    "endpoint": "http://127.0.0.1:8010/chat",
    "input": "Plan a 3-day trip to Paris with budget tips",
    "expected": None,
    "context": None,
    "metrics": ["answer_relevancy", "tool_correctness", "tool_sequence", "task_completion"],
    "expected_tool_calls": None,
    "agent_type": "orchestrator",
}
r2 = requests.post("http://127.0.0.1:8888/api/test", json=payload2, timeout=120)
d2 = r2.json()
print(f"   Score: {d2['score']}%  Metrics: {len(d2['evaluations'])}")
for ev in d2["evaluations"]:
    s = "PASS" if ev["passed"] else "FAIL"
    print(f"   {ev['metric']:25s} {ev['score']:>5.0f}%  {s}  ({ev.get('scored_by','?')})")

print("\nDone!")

# Write to file
with open("ui_fix_results.txt", "w") as f:
    f.write("RESULTS\n")
    f.write(f"New UI (auto-select): {len(d['evaluations'])} metrics, {d['score']}%\n")
    for ev in d["evaluations"]:
        s = "PASS" if ev["passed"] else "FAIL"
        f.write(f"  {ev['metric']:25s} {ev['score']:>5.0f}%  {s}  ({ev.get('scored_by','?')})\n")
    f.write(f"Old UI (explicit): {len(d2['evaluations'])} metrics, {d2['score']}%\n")
    for ev in d2["evaluations"]:
        s = "PASS" if ev["passed"] else "FAIL"
        f.write(f"  {ev['metric']:25s} {ev['score']:>5.0f}%  {s}  ({ev.get('scored_by','?')})\n")
print("Written to ui_fix_results.txt")
