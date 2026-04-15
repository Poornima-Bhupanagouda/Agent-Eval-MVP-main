"""Check trace/trajectory data in stored results."""
import sqlite3
import json

db = sqlite3.connect(r"C:\Users\L127256\.agent_eval\data.db")
db.row_factory = sqlite3.Row

total = db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
with_trace = db.execute(
    "SELECT COUNT(*) FROM results WHERE trajectory_data IS NOT NULL AND trajectory_data != ''"
).fetchone()[0]

print(f"Total results: {total}")
print(f"With trajectory/trace data: {with_trace}")
print(f"Without trace data: {total - with_trace}")

# Show trace samples
rows = db.execute(
    "SELECT id, endpoint, trajectory_data FROM results "
    "WHERE trajectory_data IS NOT NULL AND trajectory_data != '' "
    "ORDER BY created_at DESC LIMIT 3"
).fetchall()

if rows:
    for r in rows:
        print(f"\n{'='*60}")
        print(f"Result ID: {r['id']}")
        print(f"Endpoint:  {r['endpoint']}")
        try:
            trace = json.loads(r["trajectory_data"])
            print(f"Trace type: {type(trace).__name__}")
            print(json.dumps(trace, indent=2)[:1000])
        except:
            print(f"Raw trace: {r['trajectory_data'][:500]}")
else:
    print("\nNo results have trajectory_data.")
    print("\nTrace data is embedded in the 'evaluations' column as metric scores.")
    print("Showing evaluation trace metrics from latest result:\n")
    row = db.execute(
        "SELECT id, endpoint, evaluations FROM results ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    if row:
        print(f"Result: {row['id']} | {row['endpoint']}")
        evals = json.loads(row["evaluations"])
        print(json.dumps(evals, indent=2)[:2000])

db.close()
