"""Quick script to show what's stored in the evaluation database."""
import sqlite3, json

DB = r"C:\Users\L127256\.agent_eval\data.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print(f"Database: {DB}\n")
print("=" * 60)
print("TABLE ROW COUNTS")
print("=" * 60)
for table in ["suites", "tests", "results", "batches", "agents", "chains",
              "chain_runs", "conversation_tests", "conversation_results",
              "workflows", "baselines"]:
    try:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:30s} {count} rows")
    except:
        pass

print("\n" + "=" * 60)
print("LAST 5 EVALUATION RESULTS (most recent first)")
print("=" * 60)
rows = conn.execute(
    "SELECT id, endpoint, input, output, score, passed, latency_ms, evaluations, created_at "
    "FROM results ORDER BY created_at DESC LIMIT 5"
).fetchall()

for r in rows:
    rid = r["id"][:8]
    print(f"\n--- Result {rid}... ---")
    print(f"  Time:     {r['created_at']}")
    print(f"  Endpoint: {r['endpoint']}")
    inp = str(r["input"] or "")[:80]
    out = str(r["output"] or "")[:80]
    print(f"  Input:    {inp}")
    print(f"  Output:   {out}...")
    print(f"  Score:    {r['score']}  Passed: {bool(r['passed'])}  Latency: {r['latency_ms']}ms")

    evals = json.loads(r["evaluations"]) if r["evaluations"] else []
    print(f"  Metrics evaluated ({len(evals)}):")
    for e in evals[:6]:
        status = "PASS" if e.get("passed") else "FAIL"
        reason = str(e.get("reason", ""))[:60]
        print(f"    {status} {e['metric']}: {e['score']}% - {reason}")
    if len(evals) > 6:
        print(f"    ... and {len(evals) - 6} more metrics")

print("\n" + "=" * 60)
print("REGISTERED AGENTS")
print("=" * 60)
agents = conn.execute("SELECT id, name, endpoint, agent_type, domain FROM agents").fetchall()
for a in agents:
    print(f"  {a['name']:30s} {a['endpoint']:40s} type={a['agent_type']} domain={a['domain']}")

print("\n" + "=" * 60)
print("TEST SUITES")
print("=" * 60)
suites = conn.execute(
    "SELECT s.id, s.name, s.endpoint, COUNT(t.id) as test_count "
    "FROM suites s LEFT JOIN tests t ON s.id = t.suite_id "
    "GROUP BY s.id ORDER BY s.updated_at DESC LIMIT 10"
).fetchall()
for s in suites:
    print(f"  {s['name']:40s} tests={s['test_count']}  endpoint={s['endpoint']}")

conn.close()
