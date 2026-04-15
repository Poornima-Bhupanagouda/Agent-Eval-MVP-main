"""Quick health check for all agents."""
import httpx

checks = [
    ("Weather Agent (8004)", "http://127.0.0.1:8004/health"),
    ("Wiki Agent (8005)", "http://127.0.0.1:8005/health"),
    ("Calculator Agent (8006)", "http://127.0.0.1:8006/health"),
    ("Orchestrator (8010)", "http://127.0.0.1:8010/health"),
    ("Eval UI (8000)", "http://127.0.0.1:8000/api/health"),
]

for name, url in checks:
    try:
        r = httpx.get(url, timeout=3)
        print(f"  {name}: {'OK' if r.status_code == 200 else f'HTTP {r.status_code}'}")
    except httpx.ConnectError:
        print(f"  {name}: NOT RUNNING")
    except Exception as e:
        print(f"  {name}: ERROR - {e}")
