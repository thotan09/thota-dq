"""
Thota DQ — Real-World End-to-End Demo
======================================

Scenario: RetailCo e-commerce platform with 5 interconnected tables.
          Realistic dirty data injected to trigger every pipeline node.

Pipeline nodes exercised:
  plan           → parse 12 rules, build execution order
  parallel_table → fan-out: orders, customers, payments, products run concurrently
  classify       → LLM triages severity of each failure
  diagnose       → LLM explains each failure in plain English
  rca            → LLM performs root-cause analysis with lineage context
  reconcile      → compare results against thresholds
  remediate      → LLM proposes concrete fix steps
  report         → structured JSON + rich console output

Run:
    python demo/realworld_demo.py
    python demo/realworld_demo.py --no-llm          # validation only, no LLM cost
    python demo/realworld_demo.py --output report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import duckdb
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()


# ---------------------------------------------------------------------------
# 1. Build the demo warehouse
# ---------------------------------------------------------------------------

def build_demo_warehouse(db_path: str = ":memory:") -> duckdb.DuckDBPyConnection:
    """Create a RetailCo demo database with realistic dirty data."""
    conn = duckdb.connect(db_path)

    conn.execute("""
        CREATE TABLE customers (
            customer_id   INTEGER,
            email         VARCHAR,
            name          VARCHAR,
            country       VARCHAR,
            created_at    TIMESTAMP,
            tier          VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO customers VALUES
          (1,  'alice@example.com',   'Alice Martin',  'US', '2023-01-15 09:00:00', 'gold'),
          (2,  'bob@example.com',     'Bob Chen',      'UK', '2023-02-20 14:30:00', 'silver'),
          (3,  NULL,                  'Carol White',   'DE', '2023-03-10 11:00:00', 'bronze'),
          (4,  'david@example.com',   'David Kim',     'US', '2023-04-01 08:45:00', 'gold'),
          (5,  'eve@example.com',     'Eve Lopez',     'FR', '2023-05-12 16:00:00', 'platinum'),
          (6,  'frank@example.com',   NULL,            'AU', '2023-06-01 10:00:00', 'silver'),
          (7,  '',                    'Grace Hall',    'CA', '2023-06-15 12:00:00', 'bronze'),
          (8,  'henry@example.com',   'Henry Adams',   'US', '2023-07-04 09:30:00', 'vip'),
          (9,  'ida@example.com',     'Ida Watson',    'US', '2023-07-20 11:15:00', 'gold'),
          (10, 'jack@example.com',    'Jack Brown',    'UK', '2023-08-01 14:00:00', 'silver')
    """)

    conn.execute("""
        CREATE TABLE products (
            product_id    INTEGER,
            sku           VARCHAR,
            name          VARCHAR,
            category      VARCHAR,
            price         FLOAT,
            stock_qty     INTEGER,
            last_updated  TIMESTAMP
        )
    """)
    conn.execute("""
        INSERT INTO products VALUES
          (1,  'SKU-001', 'Laptop Pro 15',     'electronics', 1299.99,  45,  '2024-01-10 08:00:00'),
          (2,  'SKU-002', 'Wireless Headset',  'electronics',   89.99, 120,  '2024-01-12 09:00:00'),
          (3,  'SKU-003', 'Office Chair',      'furniture',    299.00,  18,  '2024-01-08 10:00:00'),
          (4,  'SKU-004', 'Standing Desk',     'furniture',    549.00,   7,  '2024-01-05 11:00:00'),
          (5,  'SKU-005', 'Coffee Maker',      'appliances',  -49.99,  32,  '2024-01-11 12:00:00'),
          (6,  'SKU-006', 'Notebook Set',      'stationery',    12.99, 200,  '2024-01-09 13:00:00'),
          (7,  'SKU-007', 'USB-C Hub',         'electronics',   39.99,  67,  '2024-01-07 14:00:00'),
          (8,  'SKU-008', 'Monitor 27"',       'electronics',  399.00,  23,  '2024-01-06 15:00:00'),
          (9,  'SKU-001', 'Laptop Pro 15 v2',  'electronics', 1399.99,  10,  '2024-01-13 08:00:00'),
          (10, 'SKU-010', 'Mechanical Keyboard','electronics',  129.00, -5,  '2024-01-04 16:00:00')
    """)

    conn.execute("""
        CREATE TABLE orders (
            order_id      INTEGER,
            customer_id   INTEGER,
            order_date    TIMESTAMP,
            ship_date     TIMESTAMP,
            status        VARCHAR,
            total_amount  FLOAT,
            currency      VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO orders VALUES
          (1001, 1,  '2024-01-15 10:00:00', '2024-01-17 14:00:00', 'shipped',    1389.98, 'USD'),
          (1002, 2,  '2024-01-16 11:30:00', '2024-01-18 09:00:00', 'shipped',      89.99, 'GBP'),
          (1003, 3,  '2024-01-17 14:00:00', '2024-01-19 11:00:00', 'delivered',   299.00, 'EUR'),
          (1004, 4,  '2024-01-18 09:00:00', '2024-01-15 08:00:00', 'shipped',     549.00, 'USD'),
          (1005, 5,  '2024-01-19 16:00:00', NULL,                   'pending',     159.98, 'EUR'),
          (1006, 99, '2024-01-20 10:00:00', '2024-01-22 12:00:00', 'shipped',    -99.99, 'USD'),
          (1007, 7,  '2024-01-21 08:30:00', '2024-01-23 10:00:00', 'cancelled',   549.00, 'CAD'),
          (1008, 8,  '2024-01-22 12:00:00', '2024-01-24 14:00:00', 'DISPATCHED',  399.00, 'USD'),
          (1009, 9,  '2024-01-23 09:00:00', '2024-01-25 11:00:00', 'shipped',    129.00, 'USD'),
          (1010, 10, '2024-01-24 15:00:00', '2024-01-26 09:00:00', 'delivered',   12.99, 'GBP')
    """)

    conn.execute("""
        CREATE TABLE payments (
            payment_id    INTEGER,
            order_id      INTEGER,
            amount        FLOAT,
            method        VARCHAR,
            processed_at  TIMESTAMP,
            status        VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO payments VALUES
          (5001, 1001,  1389.98, 'credit_card', '2024-01-15 10:05:00', 'completed'),
          (5002, 1002,    89.99, 'paypal',       '2024-01-16 11:35:00', 'completed'),
          (5003, 1003,   299.00, 'credit_card',  '2024-01-17 14:05:00', 'completed'),
          (5004, 1004,   549.00, 'bank_transfer','2024-01-18 09:05:00', 'completed'),
          (5005, 1005,   159.98, 'credit_card',  '2024-01-19 16:05:00', 'pending'),
          (5006, 9999,   250.00, 'crypto',       '2024-01-20 10:05:00', 'completed'),
          (5007, 1007,  -549.00, 'refund',        '2024-01-21 08:35:00', 'completed'),
          (5008, 1008,   399.00, 'credit_card',  '2024-01-22 12:05:00', 'completed'),
          (5009, 1009,   129.00, 'paypal',        '2024-01-23 09:05:00', 'completed'),
          (5010, 1010,    12.99, 'credit_card',  '2024-01-24 15:05:00', 'completed')
    """)

    return conn


# ---------------------------------------------------------------------------
# 2. Define the rules
# ---------------------------------------------------------------------------

def build_rules():
    from thota_dq.rules.schema import DataQualityRule

    specs = [
        # ── CUSTOMERS ────────────────────────────────────────────────────
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "customers_email_not_null", "severity": "critical",
                         "owner": "data-platform", "tags": ["completeness", "pii"]},
            "scope": {"table": "customers", "columns": ["email"]},
            "logic": {"type": "not_null"},
            "diagnosis": {"common_causes": ["ETL skipped email validation", "source system allows NULL emails"],
                          "lineage_hints": {"customers": ["email", "customer_id"]}},
        },
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "customers_email_not_empty", "severity": "high",
                         "owner": "data-platform", "tags": ["completeness", "pii"]},
            "scope": {"table": "customers", "columns": ["email"]},
            "logic": {"type": "not_empty_string"},
            "diagnosis": {"common_causes": ["Source system written empty string instead of NULL",
                                            "Form validation bypassed"]},
        },
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "customers_tier_accepted", "severity": "medium",
                         "owner": "crm-team", "tags": ["validity", "classification"]},
            "scope": {"table": "customers", "columns": ["tier"]},
            "logic": {"type": "accepted_values",
                      "values": ["bronze", "silver", "gold", "platinum"]},
            "diagnosis": {"common_causes": ["New tier added to source system without schema update",
                                            "Manual data entry typo"]},
        },
        # ── PRODUCTS ────────────────────────────────────────────────────
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "products_price_positive", "severity": "critical",
                         "owner": "catalog-team", "tags": ["validity", "financial"]},
            "scope": {"table": "products", "columns": ["price"]},
            "logic": {"type": "sql_expression", "expression": "price > 0"},
            "diagnosis": {"common_causes": ["Negative price from promo code bug",
                                            "Refund record misclassified as product price"],
                          "lineage_hints": {"products": ["price", "sku"]}},
        },
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "products_sku_unique", "severity": "critical",
                         "owner": "catalog-team", "tags": ["uniqueness"]},
            "scope": {"table": "products", "columns": ["sku"]},
            "logic": {"type": "unique"},
            "diagnosis": {"common_causes": ["Product versioning reused old SKU",
                                            "Duplicate import from supplier feed"]},
        },
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "products_stock_non_negative", "severity": "high",
                         "owner": "inventory-team", "tags": ["validity"]},
            "scope": {"table": "products", "columns": ["stock_qty"]},
            "logic": {"type": "min_value_check", "min_value": 0},
            "diagnosis": {"common_causes": ["Oversell in flash sale without inventory lock",
                                            "Warehouse adjustment applied twice"]},
        },
        # ── ORDERS ───────────────────────────────────────────────────────
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "orders_amount_positive", "severity": "critical",
                         "owner": "finance-team", "tags": ["validity", "financial"]},
            "scope": {"table": "orders", "columns": ["total_amount"]},
            "logic": {"type": "sql_expression", "expression": "total_amount > 0"},
            "diagnosis": {"common_causes": ["Refund order written to orders table",
                                            "Currency conversion sign error"],
                          "lineage_hints": {"payments": ["amount", "order_id"],
                                            "products": ["price"]}},
        },
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "orders_status_valid", "severity": "high",
                         "owner": "ops-team", "tags": ["validity"]},
            "scope": {"table": "orders", "columns": ["status"]},
            "logic": {"type": "accepted_values",
                      "values": ["pending", "shipped", "delivered", "cancelled", "returned"]},
            "diagnosis": {"common_causes": ["Carrier system uses non-standard status codes",
                                            "Legacy migration not normalised"]},
        },
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "orders_date_order", "severity": "high",
                         "owner": "ops-team", "tags": ["timeliness"]},
            "scope": {"table": "orders", "columns": ["order_date"]},
            "logic": {"type": "date_order", "column_b": "ship_date"},
            "diagnosis": {"common_causes": ["Timezone conversion error flipped dates",
                                            "Backfilled ship_date used wrong reference"]},
        },
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "orders_customer_fk", "severity": "critical",
                         "owner": "data-platform", "tags": ["referential"]},
            "scope": {"table": "orders", "columns": ["customer_id"]},
            "logic": {"type": "foreign_key",
                      "reference_table": "customers", "reference_column": "customer_id"},
            "diagnosis": {"common_causes": ["Order created for deleted/test customer account",
                                            "Cross-environment data migration brought wrong IDs"],
                          "lineage_hints": {"customers": ["customer_id"]}},
        },
        # ── PAYMENTS ────────────────────────────────────────────────────
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "payments_amount_non_zero", "severity": "critical",
                         "owner": "finance-team", "tags": ["validity", "financial"]},
            "scope": {"table": "payments", "columns": ["amount"]},
            "logic": {"type": "sql_expression", "expression": "amount != 0"},
            "diagnosis": {"common_causes": ["Refund processed as negative amount instead of separate credit",
                                            "Pending payment inserted before amount resolved"],
                          "lineage_hints": {"orders": ["total_amount", "order_id"]}},
        },
        {
            "apiVersion": "thota_dq.dev/v1", "kind": "DataQualityRule",
            "metadata": {"id": "payments_order_fk", "severity": "critical",
                         "owner": "finance-team", "tags": ["referential"]},
            "scope": {"table": "payments", "columns": ["order_id"]},
            "logic": {"type": "foreign_key",
                      "reference_table": "orders", "reference_column": "order_id"},
            "diagnosis": {"common_causes": ["Payment gateway sent callback for cancelled/test order",
                                            "Duplicate payment IDs from retry storm"]},
        },
    ]

    return [DataQualityRule.model_validate(s) for s in specs]


# ---------------------------------------------------------------------------
# 3. Pretty-print the report
# ---------------------------------------------------------------------------

def print_banner(llm_model: str | None):
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Thota DQ[/bold cyan]  [dim]—[/dim]  [white]RetailCo E-commerce Demo[/white]\n"
        f"[dim]LLM: {llm_model or 'none (validation only)'}[/dim]",
        border_style="cyan",
    ))
    console.print()


def print_pipeline_state(final):
    rules      = final.get("rules", [])
    results    = final.get("rule_results", [])
    failures   = final.get("failures", [])
    classified = final.get("classified_failures", {})
    diagnoses  = final.get("diagnoses", [])
    rca        = final.get("rca_results", [])
    remediation= final.get("remediation_proposals", [])
    report     = final.get("report", {})
    cost       = final.get("cost_total_usd", 0.0)
    tokens     = final.get("tokens_total", 0)

    # ── Summary card ────────────────────────────────────────────────────
    summary = report.get("summary", {})
    total   = summary.get("total_rules", len(results))
    passed  = summary.get("passed", sum(1 for r in results if r.passed))
    failed  = summary.get("failed", sum(1 for r in results if not r.passed))
    pct     = f"{passed/total*100:.0f}%" if total else "—"

    t = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    t.add_column("Metric", style="dim")
    t.add_column("Value", style="bold")
    t.add_row("Rules checked", str(total))
    t.add_row("Passed", f"[green]{passed}[/green]")
    t.add_row("Failed", f"[red]{failed}[/red]")
    t.add_row("Pass rate", pct)
    if cost > 0:
        t.add_row("LLM cost", f"${cost:.6f}")
    if tokens > 0:
        t.add_row("Total tokens", f"{tokens:,}")
    console.print(Panel(t, title="[bold]Validation Summary[/bold]", border_style="green" if failed == 0 else "red"))
    console.print()

    # ── Per-table results ─────────────────────────────────────────────
    tables = sorted({r.rule.spec_scope.table for r in failures} |
                    {r.rule_id.split("_")[0] for r in results})
    table_results: dict[str, list] = {}
    for r in results:
        tbl = next((f.rule.spec_scope.table for f in failures if f.result.rule_id == r.rule_id),
                   r.rule_id.split("_")[0])
        table_results.setdefault(tbl, []).append(r)

    for r in results:
        tbl = next(
            (f.rule.spec_scope.table for f in (final.get("failures") or []) if f.result.rule_id == r.rule_id),
            None
        )
        if tbl is None:
            tbl = r.rule_id.rsplit("_", 1)[0] if "_" in r.rule_id else "unknown"
        table_results.setdefault(tbl, []).append(r)

    # ── Classified failures ─────────────────────────────────────────
    if classified:
        console.print("[bold]Failures by Severity[/bold]")
        for sev, flist in classified.items():
            color = {"critical": "red", "high": "yellow", "medium": "blue",
                     "low": "green", "info": "dim"}.get(sev, "white")
            console.print(f"  [{color}]● {sev.upper()}[/{color}]  ({len(flist)} rule{'s' if len(flist)>1 else ''})")
            for f in flist:
                console.print(f"    [dim]↳[/dim] {f.rule.metadata.id}  [dim]({f.rule.spec_scope.table})[/dim]")
        console.print()

    # ── Diagnoses ────────────────────────────────────────────────────
    if diagnoses:
        console.print(Panel("[bold]LLM Diagnoses[/bold]", border_style="yellow"))
        diag_map = {d["failure_id"]: d for d in diagnoses}
        for failure in (final.get("failures") or []):
            rid = failure.rule.metadata.id
            d   = diag_map.get(rid)
            if not d:
                continue
            sev = str(failure.rule.metadata.severity)
            color = {"critical": "red", "high": "yellow", "medium": "blue"}.get(sev, "white")
            console.print(f"\n  [bold {color}]{rid}[/bold {color}]  [dim]→ {failure.rule.spec_scope.table}[/dim]")
            console.print(f"  [dim]Rows checked:[/dim] {failure.result.row_count_checked}  "
                          f"[dim]Failed:[/dim] [red]{failure.result.row_count_failed}[/red]")
            console.print(f"  [yellow]Explanation:[/yellow]  {d.get('explanation', '—')}")
            console.print(f"  [red]Likely cause:[/red]  {d.get('likely_cause', '—')}")
            console.print(f"  [green]Action:[/green]       {d.get('suggested_action', '—')}")
        console.print()

    # ── RCA ──────────────────────────────────────────────────────────
    if rca:
        console.print(Panel("[bold]Root-Cause Analysis[/bold]", border_style="magenta"))
        for r in rca:
            console.print(f"\n  [bold magenta]{r.get('failure_id', '?')}[/bold magenta]  "
                          f"[dim]({r.get('table', '')})[/dim]")
            console.print(f"  [dim]Root cause:[/dim]   {r.get('root_cause', '—')}")
            console.print(f"  [dim]Origin:[/dim]       {r.get('origin', '—')}")
            console.print(f"  [dim]Propagation:[/dim]  {r.get('propagation', '—')}")
            console.print(f"  [green]Fix:[/green]          {r.get('fix', '—')}")
            upstreams = r.get("upstream_tables", [])
            if upstreams:
                console.print(f"  [dim]Upstream:[/dim]     {', '.join(upstreams)}")
        console.print()

    # ── Remediation ──────────────────────────────────────────────────
    if remediation:
        console.print(Panel("[bold]Remediation Proposals (LLM-generated SQL)[/bold]", border_style="green"))
        for prop in remediation:
            fid  = prop.get("failure_id", "?")
            sql  = prop.get("proposed_sql", "—")
            conf = prop.get("confidence", "?")
            cav  = prop.get("caveat", "")
            conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(conf, "white")
            console.print(f"\n  [bold]{fid}[/bold]  [dim]({prop.get('table','')}.{prop.get('rule_type','')})[/dim]")
            console.print(f"  [cyan]{sql}[/cyan]")
            console.print(f"  [{conf_color}]Confidence: {conf}[/{conf_color}]  [dim]⚠ {cav}[/dim]")
        console.print()

    # ── Reconciliation ───────────────────────────────────────────────
    recon = final.get("reconciliation_summary", {})
    if recon:
        console.print(f"[dim]Reconciliation:[/dim]  {recon}")
        console.print()


# ---------------------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------------------

async def run_demo(use_llm: bool, aws_profile: str, output_path: str | None):
    from thota_dq.adapters.warehouse.duckdb import DuckDBAdapter
    from thota_dq.core.agent import AegisAgent

    print_banner(f"amazon.nova-pro-v1:0 via AWS Bedrock ({aws_profile})" if use_llm else None)

    # ── Build DuckDB fixture ────────────────────────────────────────
    console.print("[dim]Setting up RetailCo demo database...[/dim]")
    conn = build_demo_warehouse()
    adapter = DuckDBAdapter(":memory:")

    loop = asyncio.get_running_loop()
    def _copy():
        dst = adapter._get_conn()
        for tbl in ["customers", "products", "orders", "payments"]:
            df = conn.execute(f"SELECT * FROM {tbl}").df()
            dst.execute(f"CREATE TABLE {tbl} AS SELECT * FROM df")
    await loop.run_in_executor(adapter._executor, _copy)
    console.print("[green]✓[/green] Database ready: 4 tables, realistic dirty data injected\n")

    # ── Wire LLM ────────────────────────────────────────────────────
    llm = None
    if use_llm:
        from thota_dq.adapters.llm.bedrock import BedrockAdapter
        llm = BedrockAdapter(profile=aws_profile)
        console.print(f"[dim]LLM:[/dim] [cyan]{llm._model}[/cyan] via AWS Bedrock profile [cyan]{aws_profile}[/cyan]\n")

    # ── Build rules ──────────────────────────────────────────────────
    rules = build_rules()
    console.print(f"[dim]Rules loaded:[/dim] [bold]{len(rules)}[/bold] rules across "
                  f"[bold]{len({r.spec_scope.table for r in rules})}[/bold] tables\n")

    # ── Run the full pipeline ────────────────────────────────────────
    console.print("[bold cyan]Running Aegis pipeline...[/bold cyan]")
    console.print("[dim]  plan → parallel_table → reconcile → remediate → report[/dim]\n")

    agent = AegisAgent(warehouse_adapter=adapter, llm_adapter=llm)
    t0 = time.monotonic()
    final = await agent.run(rules, triggered_by="realworld-demo")
    elapsed = time.monotonic() - t0

    console.print(f"[green]✓[/green] Pipeline complete in [bold]{elapsed:.1f}s[/bold]\n")

    # ── Print results ────────────────────────────────────────────────
    print_pipeline_state(final)

    # ── Write JSON ───────────────────────────────────────────────────
    if output_path:
        out = {
            "run_id": final.get("run_id"),
            "elapsed_sec": round(elapsed, 2),
            "report": final.get("report"),
            "diagnoses": final.get("diagnoses"),
            "rca_results": final.get("rca_results"),
            "remediation_proposals": final.get("remediation_proposals"),
            "cost_total_usd": final.get("cost_total_usd"),
            "tokens_total": final.get("tokens_total"),
        }
        Path(output_path).write_text(json.dumps(out, indent=2, default=str))
        console.print(f"[dim]Full report written to:[/dim] {output_path}")

    return final


def main():
    p = argparse.ArgumentParser(description="Thota DQ real-world demo")
    p.add_argument("--no-llm", action="store_true", help="Validation only, no LLM diagnosis")
    p.add_argument("--aws-profile", default="mcal-research", help="AWS profile for Bedrock (default: mcal-research)")
    p.add_argument("--output", default=None, metavar="FILE", help="Write JSON report to file")
    args = p.parse_args()

    asyncio.run(run_demo(
        use_llm=not args.no_llm,
        aws_profile=args.aws_profile,
        output_path=args.output,
    ))


if __name__ == "__main__":
    main()
