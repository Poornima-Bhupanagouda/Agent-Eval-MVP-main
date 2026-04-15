"""Quick validation that DeepEval scoring + scored_by labels work end-to-end."""
import requests, json, sys

print("=" * 60)
print("Testing DeepEval scoring through eval platform")
print("=" * 60)

r = requests.post('http://localhost:8000/api/test', json={
    'endpoint': 'http://localhost:8002/chat',
    'input': 'What is the remote work policy?',
    'expected': 'Employees may work remotely with manager approval',
    'auth': {
        'type': 'api_key',
        'value': 'test-api-key-for-rag-agent',
        'header_name': 'X-API-Key'
    }
}, timeout=300)

print(f"\nHTTP Status: {r.status_code}")
if r.status_code != 200:
    print(f"Error: {r.text[:500]}")
    sys.exit(1)

data = r.json()
print(f"Overall Score: {data.get('score')}%")
print(f"Passed: {data.get('passed')}")
print(f"Latency: {data.get('latency_ms')}ms")
print(f"\nMetric Results:")
print("-" * 60)

has_deepeval = False
has_heuristic = False
for e in data.get('evaluations', []):
    scored_by = e.get('scored_by', 'unknown')
    if scored_by == 'deepeval':
        has_deepeval = True
    else:
        has_heuristic = True
    icon = "D" if scored_by == "deepeval" else "H"
    status = "PASS" if e['passed'] else "FAIL"
    print(f"  [{icon}] {e['metric']:25s} {e['score']:6.1f}%  {status}")
    if e.get('reason'):
        print(f"      {e['reason'][:120]}")

print("-" * 60)

# Checks
checks = []
if has_deepeval:
    checks.append("DeepEval LLM scoring: WORKING")
else:
    checks.append("DeepEval LLM scoring: MISSING")

if has_heuristic:
    checks.append("Heuristic fast scoring: WORKING")

# Toxicity should now be PASS (inverted: 0% toxic = 100% safe)
tox = [e for e in data.get('evaluations', []) if e['metric'] == 'toxicity']
if tox and tox[0]['passed']:
    checks.append("Toxicity inversion: FIXED (safe content = PASS)")
elif tox:
    checks.append(f"Toxicity inversion: STILL BROKEN (score={tox[0]['score']})")

# Similarity should be heuristic
sim = [e for e in data.get('evaluations', []) if e['metric'] == 'similarity']
if sim and sim[0].get('scored_by') == 'heuristic':
    checks.append("Similarity via heuristic: CORRECT")

for c in checks:
    print(f"  {c}")
print("=" * 60)

