"""Quick test of the /api/test endpoint."""
import httpx
import json
import time

# Test 1: Conversational agent with auto-selected metrics (includes TruLens)
payload = {
    "endpoint": "http://localhost:8003/chat",
    "input": "Hello, how are you?",
    "agent_type": "conversational",
}

print("=== Quick Test: Conversational Agent (auto metrics) ===")
start = time.time()
try:
    r = httpx.post("http://localhost:8000/api/test", json=payload, timeout=120)
    elapsed = time.time() - start
    print(f"Status: {r.status_code} in {elapsed:.1f}s")
    if r.status_code == 200:
        data = r.json()
        print(f"Output: {data['output'][:100]}")
        print(f"Score: {data['score']}, Passed: {data['passed']}")
        for ev in data["evaluations"]:
            print(f"  {ev['metric']}: {ev['score']} ({ev.get('scored_by', '?')})")
    else:
        print(f"Error: {r.text[:500]}")
except Exception as e:
    elapsed = time.time() - start
    print(f"ERROR after {elapsed:.1f}s: {e}")
