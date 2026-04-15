"""View stored test results and trace data from SQLite database."""
import sqlite3
import json

DB_PATH = r"C:\Users\L127256\.agent_eval\data.db"

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

# Show tables
print("=" * 60)
print("TABLES IN data.db")
print("=" * 60)
for t in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
    count = db.execute(f"SELECT COUNT(*) FROM [{t[0]}]").fetchone()[0]
    print(f"  {t[0]}: {count} rows")

# Show recent results with trace data
print("\n" + "=" * 60)
print("RECENT TEST RESULTS (last 10)")
print("=" * 60)

rows = db.execute(
    "SELECT r.id, r.test_id, r.suite_id, r.endpoint, r.input, r.output, "
    "r.score, r.passed, r.latency_ms, r.evaluations, r.created_at, "
    "r.trajectory_data, t.name as test_name, s.name as suite_name "
    "FROM results r "
    "LEFT JOIN tests t ON r.test_id = t.id "
    "LEFT JOIN suites s ON r.suite_id = s.id "
    "ORDER BY r.created_at DESC LIMIT 10"
).fetchall()

for r in rows:
    print(f"\n{'─' * 60}")
    print(f"  Result ID : {r['id']}")
    print(f"  Test      : {r['test_name']} (id={r['test_id']})")
    print(f"  Suite     : {r['suite_name']}")
    print(f"  Endpoint  : {r['endpoint']}")
    print(f"  Passed    : {r['passed']}   Score: {r['score']}   Latency: {r['latency_ms']}ms")
    print(f"  Date      : {r['created_at']}")

    inp = r["input"] or ""
    if len(inp) > 200:
        print(f"  Input     : {inp[:200]}...")
    else:
        print(f"  Input     : {inp}")

    resp = r["output"] or ""
    if len(resp) > 200:
        print(f"  Output    : {resp[:200]}...")
    else:
        print(f"  Output    : {resp}")

    traj = r["trajectory_data"] or ""
    if traj:
        print(f"  Trace Data: {traj[:300]}..." if len(traj) > 300 else f"  Trace Data: {traj}")

    evals = r["evaluations"]
    if evals:
        try:
            ev = json.loads(evals)
            print(f"  Metrics   : ({len(ev)} evaluated)")
            for name, data in ev.items():
                if isinstance(data, dict):
                    score = data.get("score", "?")
                    passed = data.get("passed", "?")
                    reason = data.get("reason", "")
                    line = f"    {name:30s}  score={score}  pass={passed}"
                    if reason:
                        line += f"  | {reason[:80]}"
                    print(line)
                else:
                    print(f"    {name:30s}  {data}")
        except Exception as e:
            print(f"  Evaluations (parse error): {e}")
            print(f"  Raw: {evals[:300]}")

# Show one full trace detail
print("\n" + "=" * 60)
print("FULL DETAIL OF MOST RECENT RESULT")
print("=" * 60)

row = db.execute(
    "SELECT r.*, t.name as test_name, s.name as suite_name "
    "FROM results r "
    "LEFT JOIN tests t ON r.test_id = t.id "
    "LEFT JOIN suites s ON r.suite_id = s.id "
    "ORDER BY r.created_at DESC LIMIT 1"
).fetchone()

if row:
    cols = row.keys()
    for col in cols:
        val = row[col]
        if col == "evaluations" and val:
            print(f"\n  {col}:")
            try:
                print(json.dumps(json.loads(val), indent=4))
            except:
                print(val)
        elif val and len(str(val)) > 300:
            print(f"  {col}: {str(val)[:300]}...")
        else:
            print(f"  {col}: {val}")

db.close()
print("\n✓ Database location:", DB_PATH)
