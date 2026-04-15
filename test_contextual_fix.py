"""Test contextual_relevancy fix via eval API."""
import requests, json

payload = {
    "endpoint": "http://127.0.0.1:8002/chat",
    "input": "What are the priority sectors under NITI Aayog's AI for All strategy?",
    "expected": "The priority sectors are Healthcare, Agriculture, Education, Smart Cities and Infrastructure, and Smart Mobility and Transportation.",
    "context": ["NITI AYOG mainly focused on 5 major areas: Healthcare, Agriculture, Education, Smart Cities and Infrastructure and Smart Mobility and Transportation."],
    "metrics": ["contextual_relevancy", "answer_relevancy", "faithfulness"],
    "agent_type": "rag",
}

print("Testing contextual_relevancy fix...")
try:
    r = requests.post("http://localhost:8888/api/test", json=payload, timeout=120)
    d = r.json()
    print(f"Status: {r.status_code}")
    print(f"Overall Score: {d.get('score')}%")
    print()
    for ev in d.get("evaluations", []):
        status = "PASS" if ev["passed"] else "FAIL"
        print(f"  {ev['metric']:25s} {ev['score']:>5.0f}%  {status}")
        if ev.get("reason"):
            print(f"    Reason: {ev['reason'][:150]}")
except Exception as e:
    print(f"ERROR: {e}")
