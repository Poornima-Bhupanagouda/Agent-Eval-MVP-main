"""Debug: trace the exact data flow to find why only 2 metrics appear."""
import requests, json

# Simulate exactly what the UI sends (no expected_tool_calls, no metrics = auto)
payload = {
    "endpoint": "http://127.0.0.1:8010/chat",
    "input": "Plan a 3-day trip to Paris with budget tips",
    "expected": "weather forecast, tourist attractions, country info, currency",
    "agent_type": "orchestrator",
    # UI sends null for these when auto-selected:
    "metrics": None,
    "expected_tool_calls": None,
}

print("1. Sending to eval API (same as UI)...")
r = requests.post("http://localhost:8888/api/test", json=payload, timeout=180)
d = r.json()

print(f"\n2. Response keys: {list(d.keys())}")
print(f"   trace present: {d.get('trace') is not None}")
print(f"   trace value: {d.get('trace')}")
print(f"   tool_calls present: {d.get('tool_calls') is not None}")
print(f"   tool_calls value: {d.get('tool_calls')}")
print(f"   score: {d.get('score')}%")
print(f"   num evaluations: {len(d.get('evaluations', []))}")

print(f"\n3. All metrics returned:")
for ev in d.get("evaluations", []):
    s = "PASS" if ev["passed"] else "FAIL"
    print(f"   {ev['metric']:25s} {ev['score']:>5.0f}%  {s}  ({ev.get('scored_by','?')})")

# Save to file
with open("debug_flow_out.txt", "w") as f:
    f.write(f"trace: {d.get('trace')}\n")
    f.write(f"tool_calls: {d.get('tool_calls')}\n")
    f.write(f"score: {d.get('score')}%\n")
    f.write(f"num_evals: {len(d.get('evaluations', []))}\n")
    for ev in d.get("evaluations", []):
        s = "PASS" if ev["passed"] else "FAIL"
        f.write(f"  {ev['metric']:25s} {ev['score']:>5.0f}%  {s}  ({ev.get('scored_by','?')})\n")
print("Saved to debug_flow_out.txt")
