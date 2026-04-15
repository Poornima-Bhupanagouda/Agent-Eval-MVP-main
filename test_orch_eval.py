import requests, json

payload = {
    "endpoint": "http://127.0.0.1:8010/chat",
    "input": "Plan a trip to Tokyo",
    "expected": "travel briefing for Tokyo with weather, attractions, and country info",
    "metrics": ["answer_relevancy", "tool_correctness", "tool_args_accuracy", "tool_sequence", "node_success_rate", "step_latency", "agent_reasoning"],
    "agent_type": "orchestrator",
    "expected_tool_calls": [
        {"tool": "route_to_agent", "args": {"agent": "weather_agent"}},
        {"tool": "route_to_agent", "args": {"agent": "wiki_agent"}},
        {"tool": "route_to_agent", "args": {"agent": "calculator_agent"}},
    ],
}
try:
    r = requests.post("http://localhost:8888/api/test", json=payload, timeout=180)
    d = r.json()
    print("status:", r.status_code)
    print("score:", d.get("score"))
    for ev in d.get("evaluations", []):
        status = "PASS" if ev["passed"] else "FAIL"
        print(f"  {ev['metric']:25s} {ev['score']:>5.0f}%  {status}")
    if d.get("tool_calls"):
        print("\ntool_calls:")
        for tc in d["tool_calls"]:
            print(f"  {json.dumps(tc)}")
except Exception as e:
    print("ERROR:", e)
