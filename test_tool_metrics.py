"""Quick test to verify tool metrics work end-to-end."""
import requests
import json

r = requests.post('http://localhost:8888/api/test', json={
    'endpoint': 'http://localhost:8010/chat',
    'input': 'Plan a 5-day trip to Tokyo',
    'expected': 'Tokyo, weather, temperature, Japan, tourism',
    'metrics': ['answer_relevancy', 'task_completion', 'tool_correctness', 'tool_args_accuracy', 'tool_sequence'],
    'expected_tool_calls': [
        {'tool': 'route_to_agent', 'args': {'agent': 'weather_agent'}},
        {'tool': 'route_to_agent', 'args': {'agent': 'wiki_agent'}},
        {'tool': 'route_to_agent', 'args': {'agent': 'calculator_agent'}}
    ],
    'agent_type': 'orchestrator'
})

data = r.json()
print(f"Status: {r.status_code}")
print(f"Score: {data.get('score')}")
print(f"Passed: {data.get('passed')}")
print(f"Tool calls found: {len(data.get('tool_calls') or [])}")
if data.get('tool_calls'):
    for tc in data['tool_calls']:
        print(f"  -> {tc}")
print()
for ev in data.get('evaluations', []):
    status = "PASS" if ev["passed"] else "FAIL"
    reason = ev["reason"][:100]
    print(f"  {ev['metric']}: {ev['score']}% {status} ({ev['scored_by']}) - {reason}")
