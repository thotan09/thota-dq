#!/usr/bin/env bash
# Demo script — seeds DuckDB and runs thota-dq (no LLM key required)
# Record with: asciinema rec demo.cast && agg demo.cast demo.gif

set -e
cd "$(dirname "$0")"

echo "Setting up demo data..."
python3 - <<'EOF'
import duckdb, os
db_path = "/tmp/thota-dq_demo.db"
if os.path.exists(db_path):
    os.remove(db_path)
con = duckdb.connect(db_path)
con.execute("""
    CREATE TABLE orders AS
    SELECT i AS order_id, 'placed' AS status, i * 9.99 AS revenue
    FROM range(1, 10001) t(i)
""")
con.execute("UPDATE orders SET order_id = NULL WHERE order_id % 200 = 0")
con.execute("UPDATE orders SET revenue = -5.00 WHERE order_id % 500 = 0")
con.close()
print("Demo database ready: /tmp/thota-dq_demo.db (10,000 orders, 50 nulls, 20 bad revenue)")
EOF

echo ""
echo "Running thota-dq validate..."
thota-dq validate "$(dirname "$0")/rules.yaml"

echo ""
echo "Running thota-dq run (offline, no LLM key needed)..."
thota-dq run "$(dirname "$0")/rules.yaml" --db /tmp/thota-dq_demo.db --no-llm || true

echo ""
echo "Run complete. Audit trail:"
thota-dq audit list-runs
