"""
Aegis demo — run with: python examples/retail_basic/demo.py

Creates an in-memory DuckDB table with intentional data quality failures,
then runs Aegis validation with LLM diagnosis disabled so no API key is needed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
from thota_dq.core.agent import AegisAgent
from thota_dq.rules.parser import load_rules


async def main() -> None:
    # ------------------------------------------------------------------ #
    # 1. Set up an in-memory DuckDB with intentional failures              #
    # ------------------------------------------------------------------ #
    adapter = DuckDBAdapter(":memory:")
    conn = adapter._get_conn()
    conn.execute(
        "CREATE TABLE orders (order_id INT, revenue FLOAT, customer_id INT)"
    )
    conn.execute(
        """
        INSERT INTO orders VALUES
        (1,  100.0, 10),
        (2,  -50.0, 11),    -- negative revenue  → fails orders_revenue_positive
        (3,  200.0, 12),
        (NULL, 75.0, 13)    -- null order_id      → fails orders_order_id_not_null
        """
    )

    # ------------------------------------------------------------------ #
    # 2. Load rules and run the agent (--no-llm so no API key needed)     #
    # ------------------------------------------------------------------ #
    rules_path = Path(__file__).parent / "rules.yaml"
    rules = load_rules(rules_path)

    # Pass llm_adapter=None to skip diagnosis (offline / demo mode)
    agent = AegisAgent(warehouse_adapter=adapter, llm_adapter=None)
    final_state = await agent.run(rules, triggered_by="demo_script")

    # ------------------------------------------------------------------ #
    # 3. Print a simple summary                                            #
    # ------------------------------------------------------------------ #
    report = final_state["report"]
    s = report["summary"]

    print("\n" + "=" * 60)
    print("Aegis Demo — Validation Report")
    print("=" * 60)
    print(
        f"Rules: {s['total_rules']}  "
        f"Passed: {s['passed']}  "
        f"Failed: {s['failed']}  "
        f"({s['pass_rate']}%)"
    )

    for f in report.get("failures", []):
        print(f"\nFAILED: {f['rule_id']} (severity={f['severity']})")
        print(f"  Table   : {f['table']}")
        print(f"  Rows    : {f['rows_failed']} failed / {f['rows_checked']} checked")
        if "diagnosis" in f:
            print(f"  Explain : {f['diagnosis']['explanation']}")
        if "error" in f:
            print(f"  Error   : {f['error']}")

    print("\nRun ID :", report["run_id"])
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
