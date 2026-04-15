import requests, json, sys
r = requests.post('http://localhost:8000/api/test', json={
    'endpoint': 'http://localhost:8002/chat',
    'input': 'How many paid holidays do employees get?',
    'expected': '11 paid holidays',
    'auth': {'type': 'api_key', 'value': 'test-api-key-for-rag-agent', 'header_name': 'X-API-Key'}
}, timeout=300)
d = r.json()
print('Status:', r.status_code, flush=True)
print('Score:', d.get('score'), flush=True)
print('Num evals:', len(d.get('evaluations', [])), flush=True)
for e in d.get('evaluations', []):
    sb = e.get('scored_by', '?')
    m = e['metric']
    s = e['score']
    reason = e.get('reason', '')[:80]
    print(f'  {sb} | {m}: {s}% | {reason}', flush=True)
sys.exit(0)
