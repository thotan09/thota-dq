"""Thota DQ CLI — main entry point."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

# Redirect warnings to logging and silence — LangChain installs its own
# warning filters at import time that would shadow filterwarnings() calls.
logging.captureWarnings(True)
logging.getLogger("py.warnings").addHandler(logging.NullHandler())
logging.getLogger("py.warnings").propagate = False

app = typer.Typer(help="Thota DQ — agentic data quality framework")
console = Console()

rules_app = typer.Typer(help="Manage built-in rule templates")
app.add_typer(rules_app, name="rules")


@app.command()
def init(
    directory: Path = typer.Argument(
        Path("."), help="Project directory to initialise (default: current dir)"
    ),
    name: str = typer.Option("my-pipeline", "--name", "-n", help="Name for the example pipeline"),
    warehouse: str = typer.Option("duckdb", "--warehouse", "-w", help="Default warehouse type"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files"),
) -> None:
    """Scaffold a new Thota DQ project — creates thota-dq.yaml, folder structure, and a starter pipeline."""
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)

    aegis_yaml = directory / "thota-dq.yaml"
    gitignore = directory / ".gitignore"
    pipeline_dir = directory / "pipelines" / name
    pipeline_yaml = pipeline_dir / "pipeline.yaml"
    rules_yaml = pipeline_dir / "rules.yaml"
    aegis_dir = directory / ".thota_dq"

    # --- thota-dq.yaml ---
    if not aegis_yaml.exists() or force:
        warehouse_block = {
            "duckdb": "  type: duckdb\n  connection:\n    path: .thota_dq/data.duckdb",
            "bigquery": "  type: bigquery\n  connection:\n    project: my-gcp-project\n    dataset: analytics",
            "postgres": "  type: postgres\n  connection:\n    dsn: postgresql://user:pass@localhost:5432/mydb",
            "athena": "  type: athena\n  connection:\n    s3_staging_dir: s3://my-bucket/athena/\n    region_name: us-east-1",
            "databricks": "  type: databricks\n  connection:\n    server_hostname: abc.azuredatabricks.net\n    http_path: /sql/1.0/warehouses/abc\n    access_token: dapi...",
        }.get(warehouse, f"  type: {warehouse}\n  connection: {{}}")

        aegis_yaml.write_text(f"""\
# thota-dq.yaml — Project-level configuration. Commit this file.
# Credentials and secrets go in environment variables, never here.
# Each pipeline inherits these defaults and can override any field.

default_llm:
  provider: anthropic          # anthropic | openai | bedrock | ollama
  model: claude-haiku-4-5-20251001

default_warehouse:
{warehouse_block}

audit:
  db_path: .thota_dq/history.db  # local audit trail — do not commit

pipelines_dir: pipelines
""")
        console.print(f"[green]✓[/green] {aegis_yaml.relative_to(directory)}")
    else:
        console.print(
            f"[yellow]~[/yellow] {aegis_yaml.relative_to(directory)} (already exists, skipped)"
        )

    # --- pipelines/<name>/ ---
    pipeline_dir.mkdir(parents=True, exist_ok=True)

    if not pipeline_yaml.exists() or force:
        pipeline_yaml.write_text(f"""\
# pipelines/{name}/pipeline.yaml
# Warehouse and LLM are inherited from thota_dq.yaml unless overridden here.

name: {name}
description: "Data quality checks for {name}"
rules: ./rules.yaml

goal: |
  Run all data quality rules. For every failure:
    - Explain what the failure means in plain English
    - Identify the most likely root cause
    - Propose a concrete remediation action
  Group findings by severity: CRITICAL → HIGH → MEDIUM.

# Uncomment to use a different warehouse for this pipeline:
# warehouse:
#   type: bigquery
#   connection:
#     project: other-project
#     dataset: other-dataset

# Uncomment to attach policy or schema docs for LLM context:
# kb:
#   - ./policy.md
#   - ./schema.md
""")
        console.print(f"[green]✓[/green] pipelines/{name}/pipeline.yaml")
    else:
        console.print(
            f"[yellow]~[/yellow] pipelines/{name}/pipeline.yaml (already exists, skipped)"
        )

    if not rules_yaml.exists() or force:
        rules_yaml.write_text(f"""\
# pipelines/{name}/rules.yaml
# Add your data quality rules here. Run `thota-dq validate ./rules.yaml` to check syntax.
rules:
  - apiVersion: thota_dq.dev/v1
    kind: DataQualityRule
    metadata:
      id: example_not_null
      severity: critical
    scope:
      table: my_table
      columns: [id]
    logic:
      type: not_null

  - apiVersion: thota_dq.dev/v1
    kind: DataQualityRule
    metadata:
      id: example_positive_amount
      severity: high
    scope:
      table: my_table
    logic:
      type: sql_expression
      expression: "amount >= 0"
""")
        console.print(f"[green]✓[/green] pipelines/{name}/rules.yaml")
    else:
        console.print(f"[yellow]~[/yellow] pipelines/{name}/rules.yaml (already exists, skipped)")

    # --- .thota_dq/ ---
    aegis_dir.mkdir(exist_ok=True)
    (aegis_dir / ".gitkeep").touch()

    # --- .gitignore ---
    gitignore_entries = [".thota_dq/history.db", ".thota_dq/*.duckdb", ".env", "*.duckdb"]
    if not gitignore.exists() or force:
        gitignore.write_text("\n".join(gitignore_entries) + "\n")
        console.print("[green]✓[/green] .gitignore")
    else:
        # Append missing entries without overwriting
        existing = gitignore.read_text()
        missing = [e for e in gitignore_entries if e not in existing]
        if missing:
            gitignore.write_text(existing.rstrip() + "\n" + "\n".join(missing) + "\n")
            console.print(f"[green]✓[/green] .gitignore (appended {len(missing)} entries)")
        else:
            console.print("[yellow]~[/yellow] .gitignore (already up to date)")

    console.print()
    console.print("[bold]Project ready.[/bold] Next steps:")
    console.print(
        f"  1. Edit [cyan]pipelines/{name}/rules.yaml[/cyan] with your actual table and column names"
    )
    console.print("  2. Set your LLM key:  [cyan]export ANTHROPIC_API_KEY=sk-ant-...[/cyan]")
    console.print(
        f"  3. Validate syntax:   [cyan]thota-dq validate pipelines/{name}/rules.yaml[/cyan]"
    )
    console.print(
        f"  4. Run offline first: [cyan]thota-dq pipeline run pipelines/{name}/pipeline.yaml --no-llm[/cyan]"
    )
    console.print(
        f"  5. Full run with LLM: [cyan]thota-dq pipeline run pipelines/{name}/pipeline.yaml[/cyan]"
    )
    if warehouse != "duckdb":
        console.print(
            f"\n  [dim]Set {warehouse.upper()} credentials as env vars — see docs/integrations/mcp.md[/dim]"
        )


@app.command()
def run(
    config: Path = typer.Argument(..., help="Path to rules YAML file"),
    db: str = typer.Option(":memory:", "--db", help="DuckDB file path (or :memory:)"),
    warehouse: str = typer.Option("duckdb", "--warehouse", "-w", help="Warehouse: duckdb|postgres"),
    pg_dsn: str | None = typer.Option(None, "--pg-dsn", help="Postgres/Redshift DSN string"),
    pg_host: str = typer.Option("localhost", "--pg-host", help="Postgres host"),
    pg_port: int = typer.Option(5432, "--pg-port", help="Postgres port (5439 for Redshift)"),
    pg_dbname: str = typer.Option("postgres", "--pg-dbname", help="Postgres database name"),
    pg_user: str = typer.Option("postgres", "--pg-user", help="Postgres user"),
    pg_password: str = typer.Option("", "--pg-password", help="Postgres password"),
    pg_schema: str = typer.Option("public", "--pg-schema", help="Postgres default schema"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM diagnosis (offline mode)"),
    llm: str = typer.Option("anthropic", "--llm", help="LLM provider: anthropic|openai|ollama"),
    llm_model: str | None = typer.Option(None, "--llm-model", help="Override default model name"),
    ollama_host: str = typer.Option(
        "http://localhost:11434", "--ollama-host", help="Base URL for local Ollama instance"
    ),
    output_json: Path | None = typer.Option(
        None, "--output-json", "-o", help="Write JSON report to file"
    ),
    notify: str | None = typer.Option(
        None, "--notify", help="Slack webhook URL (or set AEGIS_SLACK_WEBHOOK)"
    ),
    notify_on: str = typer.Option(
        "failures", "--notify-on", help="When to notify: all|failures|critical"
    ),
) -> None:
    """Run data quality checks defined in a YAML config file."""
    asyncio.run(
        _run(
            config,
            db,
            warehouse,
            pg_dsn,
            pg_host,
            pg_port,
            pg_dbname,
            pg_user,
            pg_password,
            pg_schema,
            no_llm,
            llm,
            llm_model,
            ollama_host,
            output_json,
            notify,
            notify_on,
        )
    )


def _build_llm_adapter(
    provider: str, model: str | None, ollama_host: str = "http://localhost:11434"
):
    """Resolve provider name to an LLMAdapter instance (wrapped with retry)."""
    from ..adapters.llm.retry import RetryingLLMAdapter

    if provider == "anthropic":
        from ..adapters.llm.anthropic import AnthropicAdapter

        inner = AnthropicAdapter(**({"model": model} if model else {}))
        return RetryingLLMAdapter(inner)
    if provider == "openai":
        try:
            from ..adapters.llm.openai import OpenAIAdapter
        except ImportError:
            console.print(
                "[red]openai package not installed. Run: pip install thota-dq[openai][/red]"
            )
            raise typer.Exit(1)
        return RetryingLLMAdapter(OpenAIAdapter(**({"model": model} if model else {})))
    if provider == "ollama":
        from ..adapters.llm.ollama import OllamaAdapter

        kwargs: dict = {"base_url": ollama_host}
        if model:
            kwargs["model"] = model
        return RetryingLLMAdapter(OllamaAdapter(**kwargs))
    if provider == "bedrock":
        try:
            from ..adapters.llm.bedrock import BedrockAdapter
        except ImportError:
            console.print("[red]boto3 not installed. Run: pip install thota-dq[bedrock][/red]")
            raise typer.Exit(1)
        kwargs = {}
        if model:
            kwargs["model"] = model
        return RetryingLLMAdapter(BedrockAdapter(**kwargs))
    console.print(
        f"[red]Unknown LLM provider '{provider}'. Choose: anthropic|openai|ollama|bedrock[/red]"
    )
    raise typer.Exit(1)


def _build_warehouse_adapter(
    warehouse_type: str,
    db: str,
    pg_dsn: str | None,
    pg_host: str,
    pg_port: int,
    pg_dbname: str,
    pg_user: str,
    pg_password: str,
    pg_schema: str,
):
    if warehouse_type == "duckdb":
        from ..adapters.warehouse.duckdb import DuckDBAdapter

        return DuckDBAdapter(db)
    if warehouse_type in ("postgres", "redshift"):
        try:
            from ..adapters.warehouse.postgres import PostgresAdapter
        except ImportError:
            console.print("[red]psycopg2 not installed. Run: pip install thota-dq[postgres][/red]")
            raise typer.Exit(1)
        return PostgresAdapter(
            host=pg_host,
            port=pg_port,
            dbname=pg_dbname,
            user=pg_user,
            password=pg_password,
            schema=pg_schema,
            dsn=pg_dsn,
        )
    console.print(
        f"[red]Unknown warehouse '{warehouse_type}'. Choose: duckdb|postgres|redshift[/red]"
    )
    raise typer.Exit(1)


async def _run(
    config: Path,
    db: str,
    warehouse_type: str,
    pg_dsn: str | None,
    pg_host: str,
    pg_port: int,
    pg_dbname: str,
    pg_user: str,
    pg_password: str,
    pg_schema: str,
    no_llm: bool,
    llm_provider: str,
    llm_model: str | None,
    ollama_host: str,
    output_json: Path | None,
    notify: str | None,
    notify_on: str,
) -> None:
    from ..core.agent import AegisAgent
    from ..memory.store import save_run
    from ..rules.parser import load_rules

    console.print(f"[bold blue]Thota DQ[/bold blue] — loading rules from {config}")

    try:
        rules = load_rules(config)
    except Exception as e:
        console.print(f"[red]Failed to load rules: {e}[/red]")
        raise typer.Exit(1)

    console.print(f"Loaded [bold]{len(rules)}[/bold] rules")

    warehouse = _build_warehouse_adapter(
        warehouse_type, db, pg_dsn, pg_host, pg_port, pg_dbname, pg_user, pg_password, pg_schema
    )
    llm = None if no_llm else _build_llm_adapter(llm_provider, llm_model, ollama_host)

    if llm:
        provider_label = type(llm).__name__.replace("Adapter", "")
        model_label = getattr(llm, "_model", "")
        console.print(f"LLM: [bold]{provider_label}[/bold] ({model_label})")

    agent = AegisAgent(warehouse_adapter=warehouse, llm_adapter=llm)

    with console.status("Running validation..."):
        final_state = await agent.run(rules, triggered_by="cli")

    report = final_state["report"]

    # Print summary table
    s = report.get("summary", {})
    table = Table(title="Thota DQ Validation Report")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")
    table.add_row("Rules checked", str(s.get("total_rules", 0)))
    table.add_row("Passed", f"[green]{s.get('passed', 0)}[/green]")
    table.add_row("Failed", f"[red]{s.get('failed', 0)}[/red]")
    table.add_row("Pass rate", f"{s.get('pass_rate', 0)}%")
    if not no_llm:
        table.add_row("LLM cost", f"${report.get('cost_usd', 0):.6f}")
    console.print(table)

    # Print failures
    if report.get("failures"):
        console.print("\n[bold red]Failures:[/bold red]")
        for f in report["failures"]:
            console.print(
                f"\n  [bold]{f['rule_id']}[/bold] ([red]{f['severity']}[/red]) — {f['table']}"
            )
            console.print(f"  Rows failed: {f['rows_failed']} / {f['rows_checked']}")
            if "diagnosis" in f:
                d = f["diagnosis"]
                console.print(f"  [yellow]Explanation:[/yellow] {d.get('explanation', '')}")
                console.print(f"  [yellow]Likely cause:[/yellow] {d.get('likely_cause', '')}")
                console.print(f"  [yellow]Action:[/yellow] {d.get('suggested_action', '')}")

    # Print remediation proposals
    if report.get("remediation_proposals"):
        console.print("\n[bold yellow]Remediation Proposals:[/bold yellow]")
        for p in report["remediation_proposals"]:
            label = p["failure_id"]
            console.print(f"\n  [bold]{label}[/bold] (confidence: {p['confidence']})")
            console.print(f"  [cyan]SQL:[/cyan] {p['proposed_sql']}")
            console.print(f"  [yellow]⚠[/yellow]  {p['caveat']}")

    # Save to history
    await save_run(report)

    # Write JSON if requested
    if output_json:
        output_json.write_text(json.dumps(report, indent=2))
        console.print(f"\n[green]Report written to {output_json}[/green]")

    # Slack notification
    if notify or os.environ.get("AEGIS_SLACK_WEBHOOK"):
        from ..adapters.output.slack import NotifyOn, post_to_slack

        try:
            notify_on_enum = NotifyOn(notify_on)
        except ValueError:
            console.print(
                f"[red]Invalid --notify-on value '{notify_on}'. Choose: all|failures|critical[/red]"
            )
            raise typer.Exit(1)
        sent = await post_to_slack(report, webhook_url=notify, notify_on=notify_on_enum)
        if sent:
            console.print("[green]Slack notification sent[/green]")

    # Exit with non-zero if failures
    if s.get("failed", 0) > 0:
        raise typer.Exit(1)


@app.command()
def validate(
    config: Path = typer.Argument(..., help="Path to rules YAML file"),
    warnings: bool = typer.Option(True, "--warnings/--no-warnings", help="Show warnings"),
    check_sql: bool = typer.Option(
        False, "--check-sql", help="Verify SQL syntax for sql_expression / custom_sql rules"
    ),
    db: str = typer.Option(
        "", "--db", help="DuckDB file path — enables schema-aware + dry-run SQL checks"
    ),
) -> None:
    """Check rule YAML syntax and schema correctness without hitting any warehouse.

    Add --check-sql for sqlglot syntax verification of SQL rules.
    Add --db path/to/db.duckdb to also verify column names and dry-run.
    """
    from ..rules.validator import validate_file

    conn = None
    if db:
        try:
            import duckdb

            conn = duckdb.connect(db, read_only=True)
            check_sql = True
            console.print(f"[dim]SQL check: connected to [cyan]{db}[/cyan] (read-only)[/dim]")
        except Exception as exc:
            console.print(f"[red]Could not open DB '{db}': {exc}[/red]")
            raise typer.Exit(1)
    elif check_sql:
        console.print("[dim]SQL check: syntax-only (no --db provided)[/dim]")

    report = validate_file(config, check_sql=check_sql, conn=conn)

    console.print(f"\n[bold blue]Thota DQ validate[/bold blue] — {config}\n")

    for r in report.results:
        label = r.rule_id or f"rule[{r.index}]"
        if r.valid:
            warn_str = f"  [yellow]{len(r.warnings)} warning(s)[/yellow]" if r.warnings else ""
            console.print(f"  [green]✓[/green] {label}{warn_str}")
            if warnings:
                for w in r.warnings:
                    console.print(f"      [yellow]⚠[/yellow]  {w}")
        else:
            console.print(f"  [red]✗[/red] {label}")
            for e in r.errors:
                console.print(f"      [red]✗[/red]  {e}")
            if warnings:
                for w in r.warnings:
                    console.print(f"      [yellow]⚠[/yellow]  {w}")

    console.print()
    if report.ok:
        console.print(f"[bold green]All {report.total} rule(s) valid.[/bold green]")
    else:
        console.print(
            f"[bold red]{report.invalid_count} of {report.total} rule(s) invalid.[/bold red]"
        )
        raise typer.Exit(1)


@app.command()
def generate(
    table: str = typer.Argument(..., help="Table name to generate rules for"),
    db: str = typer.Option("", "--db", help="DuckDB file path for schema introspection"),
    output: Path = typer.Option(Path("rules.yaml"), "--output", "-o", help="Output YAML file"),
    kb: list[Path] = typer.Option(
        None,
        "--kb",
        help="Knowledge-base file(s) — repeat for multiple: --kb policy.md --kb schema.md",
    ),
    provider: str = typer.Option(
        "anthropic", "--provider", help="LLM provider: anthropic | bedrock | openai | ollama"
    ),
    model: str = typer.Option(None, "--model", "-m", help="LLM model override"),
    max_rules: int = typer.Option(20, "--max-rules", help="Maximum number of rules to generate"),
    no_verify: bool = typer.Option(
        False, "--no-verify", help="Skip SQL verification of generated rules"
    ),
    save_versions: bool = typer.Option(
        False, "--save-versions", help="Persist generated rules to version store"
    ),
) -> None:
    """Generate Thota DQ rules for TABLE using an LLM.

    Introspects TABLE schema from --db (DuckDB), optionally enriches with one
    or more --kb business-context files (policy docs, schema docs, data dicts).

    Examples:
      thota-dq generate orders --db warehouse.duckdb --output orders_rules.yaml
      thota-dq generate transactions --db fraud.duckdb --kb policy.md --kb schema.md
    """
    import asyncio

    from ..rules.generator import generate_rules, introspect_table
    from ..rules.validator import validate_file

    # --- LLM ---
    llm = _build_llm_adapter(provider, model)

    # --- Schema introspection ---
    conn = None
    schema_info: dict = {"table": table, "row_count": 0, "columns": []}
    if db:
        try:
            import duckdb

            conn = duckdb.connect(db, read_only=True)
            schema_info = introspect_table(conn, table)
            col_count = len(schema_info["columns"])
            console.print(
                f"[dim]Introspected [cyan]{table}[/cyan]: "
                f"{col_count} column(s), {schema_info['row_count']:,} rows[/dim]"
            )
        except Exception as exc:
            console.print(f"[red]Could not open DB '{db}': {exc}[/red]")
            raise typer.Exit(1)
    else:
        console.print("[yellow]No --db provided — generating rules without schema stats.[/yellow]")
        schema_info = {"table": table, "row_count": 0, "columns": []}

    # --- KB context (multi-file, concatenated) ---
    kb_text: str | None = None
    if kb:
        parts: list[str] = []
        for kb_path in kb:
            if not kb_path.exists():
                console.print(f"[red]KB file not found: {kb_path}[/red]")
                raise typer.Exit(1)
            content = kb_path.read_text()
            parts.append(f"### {kb_path.name}\n{content}")
            console.print(f"[dim]Loaded KB: [cyan]{kb_path}[/cyan] ({len(content):,} chars)[/dim]")
        kb_text = "\n\n".join(parts)
        console.print(
            f"[dim]Total KB context: {len(kb_text):,} chars across {len(kb)} file(s)[/dim]"
        )

    # --- Generate ---
    console.print(f"\n[bold blue]Generating rules for [cyan]{table}[/cyan]...[/bold blue]")
    raw_yaml, rules = asyncio.run(
        generate_rules(table, schema_info, llm, kb_text=kb_text, max_rules=max_rules)
    )

    if not rules:
        console.print("[red]LLM returned no parseable rules — check your LLM config.[/red]")
        raise typer.Exit(1)

    # --- Write output ---
    output.write_text(raw_yaml)
    console.print(f"[green]Generated {len(rules)} rule(s) → {output}[/green]")

    # --- Optional SQL verification ---
    if not no_verify:
        report = validate_file(output, check_sql=True, conn=conn)
        sql_errors = sum(
            len([e for e in r.errors if e.startswith("[sql]")]) for r in report.results
        )
        if sql_errors:
            console.print(
                f"[yellow]{sql_errors} SQL issue(s) found in generated rules "
                f"— review {output} before using.[/yellow]"
            )
        else:
            console.print("[green]All generated SQL rules passed verification.[/green]")

    # --- Optional version store ---
    if save_versions:
        import asyncio as _aio

        from ..memory.rule_versions import save_rule_version

        model_id = getattr(llm, "_model", "llm/unknown")

        async def _save_all() -> None:
            for rule in rules:
                meta = rule.get("metadata", {})
                rule_id = meta.get("id", "unknown")
                version = meta.get("version", "1.0.0")
                import yaml as _yaml

                await save_rule_version(
                    rule_id=rule_id,
                    version=version,
                    status="draft",
                    yaml_content=_yaml.dump(rule, default_flow_style=False),
                    generated_by=model_id,
                )

        _aio.run(_save_all())
        console.print(f"[dim]Saved {len(rules)} rule version(s) to version store.[/dim]")

    if conn:
        conn.close()


audit_app = typer.Typer(help="Inspect audit trails and trajectories")
app.add_typer(audit_app, name="audit")

dbt_app = typer.Typer(help="dbt integration")
app.add_typer(dbt_app, name="dbt")

pipeline_app = typer.Typer(help="Named pipeline manifests — define once, run anywhere")
app.add_typer(pipeline_app, name="pipeline")


@pipeline_app.command("run")
def pipeline_run(
    manifest: Path = typer.Argument(..., help="Path to pipeline.yaml manifest"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM diagnosis"),
    output_json: Path | None = typer.Option(
        None, "--output-json", "-o", help="Override report output path"
    ),
) -> None:
    """Run a named pipeline from a pipeline.yaml manifest file."""
    from ..pipeline.manifest import PipelineManifest

    if not manifest.exists():
        console.print(f"[red]Manifest not found: {manifest}[/red]")
        raise typer.Exit(1)

    m = PipelineManifest.load(manifest)
    console.print(f"\n[bold blue]Pipeline:[/bold blue] [cyan]{m.name}[/cyan]")
    if m.description:
        console.print(f"[dim]{m.description}[/dim]")
    console.print(f"[dim]Rules  : {m.rules}[/dim]")
    console.print(f"[dim]DB     : {m.warehouse.connection.get('path', ':memory:')}[/dim]")
    if m.kb:
        console.print(f"[dim]KB     : {', '.join(m.kb)}[/dim]")

    # Build flags and delegate to run()
    out = output_json or (Path(m.output_json) if m.output_json else None)
    db = m.warehouse.connection.get("path", ":memory:")
    warehouse = m.warehouse.type
    llm_provider = m.llm.provider
    llm_model = m.llm.model

    asyncio.run(
        _run(
            config=m.rules_path(),
            db=db,
            warehouse_type=warehouse,
            pg_dsn=None,
            pg_host="localhost",
            pg_port=5432,
            pg_dbname="postgres",
            pg_user="postgres",
            pg_password="",
            pg_schema="public",
            no_llm=no_llm,
            llm_provider=llm_provider,
            llm_model=llm_model,
            ollama_host="http://localhost:11434",
            output_json=out,
            notify=None,
            notify_on="failures",
        )
    )


@pipeline_app.command("show")
def pipeline_show(
    manifest: Path = typer.Argument(..., help="Path to pipeline.yaml manifest"),
) -> None:
    """Show the contents of a pipeline manifest."""
    from rich.table import Table

    from ..pipeline.manifest import PipelineManifest

    if not manifest.exists():
        console.print(f"[red]Manifest not found: {manifest}[/red]")
        raise typer.Exit(1)

    m = PipelineManifest.load(manifest)
    table = Table(title=f"Pipeline: {m.name}", show_header=False, box=None)
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("Name", m.name)
    table.add_row("Description", m.description or "—")
    table.add_row("Rules", m.rules)
    table.add_row("Warehouse", m.warehouse.type)
    table.add_row("Database", m.warehouse.connection.get("path", ":memory:"))
    table.add_row("LLM", f"{m.llm.provider}" + (f" / {m.llm.model}" if m.llm.model else ""))
    table.add_row("KB files", "\n".join(m.kb) if m.kb else "—")
    table.add_row("Output JSON", m.output_json or "—")
    if m.goal:
        table.add_row("Goal", m.goal[:120] + ("…" if len(m.goal) > 120 else ""))
    console.print(table)


@dbt_app.command("generate")
def dbt_generate(
    manifest: Path = typer.Argument(..., help="Path to dbt manifest.json"),
    output: Path = typer.Option(Path("rules.yaml"), "--output", "-o"),
    warehouse: str = typer.Option(
        "duckdb", "--warehouse", "-w", help="Warehouse type for generated rules"
    ),
) -> None:
    """Generate Thota DQ rules YAML from a dbt manifest.json."""
    from ..integrations.dbt.parser import load_manifest, manifest_to_yaml

    if not manifest.exists():
        console.print(f"[red]Manifest not found: {manifest}[/red]")
        raise typer.Exit(1)

    try:
        mf = load_manifest(manifest)
    except Exception as e:
        console.print(f"[red]Failed to parse manifest: {e}[/red]")
        raise typer.Exit(1)

    yaml_str = manifest_to_yaml(mf)

    # Patch warehouse if user specified something other than the default
    if warehouse != "duckdb":
        yaml_str = yaml_str.replace("warehouse: duckdb", f"warehouse: {warehouse}")

    output.write_text(yaml_str)
    console.print(f"[green]Rules written to {output}[/green]")


@audit_app.command("trajectory")
def audit_trajectory(
    run_id: str = typer.Argument(..., help="Run ID to inspect"),
    fmt: str = typer.Option("table", "--format", "-f", help="Output format: table|json|sharegpt"),
) -> None:
    """Show the decision trajectory for a completed run."""
    asyncio.run(_audit_trajectory(run_id, fmt))


async def _audit_trajectory(run_id: str, fmt: str) -> None:
    from ..audit.logger import get_decisions
    from ..audit.trajectory import export_sharegpt

    if fmt == "sharegpt":
        data = await export_sharegpt(run_id)
        console.print_json(json.dumps(data, indent=2))
        return

    decisions = await get_decisions(run_id)
    if not decisions:
        console.print(f"[yellow]No decisions found for run {run_id}[/yellow]")
        raise typer.Exit(1)

    if fmt == "json":
        console.print_json(json.dumps(decisions, indent=2))
        return

    table = Table(title=f"Trajectory — {run_id}")
    table.add_column("#", style="dim", width=4)
    table.add_column("Step", style="cyan", no_wrap=True)
    table.add_column("Model", style="magenta")
    table.add_column("In tok", justify="right")
    table.add_column("Out tok", justify="right")
    table.add_column("Cost $", justify="right")
    table.add_column("ms", justify="right")
    table.add_column("Output summary", style="white")

    for i, d in enumerate(decisions, 1):
        table.add_row(
            str(i),
            d["step"],
            d.get("model") or "—",
            str(d.get("input_tokens") or 0),
            str(d.get("output_tokens") or 0),
            f"{d.get('cost_usd', 0):.6f}",
            f"{d.get('duration_ms', 0):.0f}",
            (d.get("output_summary") or "")[:60],
        )

    console.print(table)
    console.print(f"[bold]{len(decisions)}[/bold] decision(s)")


@audit_app.command("list-runs")
def audit_list_runs() -> None:
    """List all run IDs in the audit database, newest first."""
    asyncio.run(_audit_list_runs())


async def _audit_list_runs() -> None:
    from ..audit.trajectory import list_run_ids

    run_ids = await list_run_ids()
    if not run_ids:
        console.print("[yellow]No runs found in audit database[/yellow]")
        return
    for rid in run_ids:
        console.print(rid)


@audit_app.command("export-dataset")
def audit_export_dataset(
    output: Path = typer.Argument(..., help="Output file path (.jsonl or .json)"),
    run_ids: list[str] = typer.Option(
        [], "--run-id", "-r", help="Run IDs to include (repeatable); omit for all"
    ),
    fmt: str = typer.Option("jsonl", "--format", "-f", help="Output format: jsonl|json"),
    min_turns: int = typer.Option(1, "--min-turns", help="Min LLM turns per run (quality filter)"),
    no_filter: bool = typer.Option(False, "--no-filter", help="Disable quality filtering"),
) -> None:
    """Export run trajectories as a ShareGPT fine-tuning dataset."""
    asyncio.run(_audit_export_dataset(output, run_ids, fmt, min_turns, not no_filter))


async def _audit_export_dataset(
    output: Path, run_ids: list[str], fmt: str, min_turns: int, filter_quality: bool
) -> None:
    from ..audit.trajectory import export_dataset, list_run_ids

    ids = run_ids or await list_run_ids()
    if not ids:
        console.print("[yellow]No runs found[/yellow]")
        raise typer.Exit(1)

    console.print(f"Exporting [bold]{len(ids)}[/bold] run(s) → [cyan]{output}[/cyan]")
    stats = await export_dataset(
        ids, output, fmt=fmt, min_llm_turns=min_turns, filter_quality=filter_quality
    )

    console.print(
        f"[green]✓[/green] Exported [bold]{stats['exported']}[/bold] samples "
        f"({stats['skipped']} skipped by quality filter) — "
        f"{stats['total_turns']} turns, {stats['total_tokens']} tokens"
    )


@audit_app.command("search")
def audit_search(
    query: str = typer.Argument(..., help="Full-text search query"),
    run_id: str | None = typer.Option(None, "--run-id", "-r", help="Filter to specific run"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
) -> None:
    """Full-text search over audit decision trails."""
    asyncio.run(_audit_search(query, run_id, limit))


async def _audit_search(query: str, run_id: str | None, limit: int) -> None:
    from ..audit.search import search_decisions

    results = await search_decisions(query, run_id=run_id, limit=limit)
    if not results:
        console.print("[yellow]No results found[/yellow]")
        return
    table = Table(title=f"Search: {query!r}")
    table.add_column("Run ID", style="cyan")
    table.add_column("Step", style="magenta")
    table.add_column("Output", style="white")
    for r in results:
        table.add_row(r["run_id"], r["step"], (r.get("output_summary") or "")[:80])
    console.print(table)
    console.print(f"[bold]{len(results)}[/bold] result(s)")


@app.command()
def mcp(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind to"),
    port: int = typer.Option(8765, "--port", "-p", help="Port to listen on"),
    transport: str = typer.Option("stdio", "--transport", help="Transport: stdio|sse"),
) -> None:
    """Start the Thota DQ MCP server for tool use by Claude and other LLMs."""
    from .mcp_runner import run_mcp_server

    run_mcp_server(host=host, port=port, transport=transport)


@rules_app.command("list")
def rules_list(
    category: str | None = typer.Option(None, "--category", "-c", help="Filter by category"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all 30 built-in rule templates."""
    from ..rules.builtin.catalog import CATALOG

    templates = CATALOG
    if category:
        templates = [t for t in templates if t.category == category]

    if json_output:
        import dataclasses

        data = [dataclasses.asdict(t) for t in templates]
        console.print_json(json.dumps(data))
        return

    table = Table(title="Thota DQ Built-in Rule Templates")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Category", style="magenta")
    table.add_column("Description", style="white")
    table.add_column("Severity", style="yellow")

    for t in templates:
        table.add_row(t.name, t.category, t.description, t.default_severity)

    console.print(table)
    console.print(f"\n[bold]{len(templates)}[/bold] template(s) shown")


@rules_app.command("pack")
def rules_pack(
    name: str = typer.Argument(..., help="Pack name: retail"),
    output: Path = typer.Option(Path("rules.yaml"), "--output", "-o", help="Output file path"),
    orders_table: str = typer.Option("orders", "--orders-table", help="Override orders table name"),
    order_items_table: str = typer.Option(
        "order_items", "--order-items-table", help="Override order_items table name"
    ),
    products_table: str = typer.Option(
        "products", "--products-table", help="Override products table name"
    ),
    customers_table: str = typer.Option(
        "customers", "--customers-table", help="Override customers table name"
    ),
    warehouse: str = typer.Option("duckdb", "--warehouse", "-w", help="Warehouse type"),
) -> None:
    """Export a built-in industry pack as a rules YAML file."""
    if name != "retail":
        console.print(f"[red]Unknown pack '{name}'. Available: retail[/red]")
        raise typer.Exit(1)

    src = Path(__file__).parent.parent / "rules" / "builtin" / "packs" / "retail.yaml"
    text = src.read_text()

    # Substitute canonical table names with caller's actual names.
    text = text.replace("table: orders\n", f"table: {orders_table}\n")
    text = text.replace("table: order_items\n", f"table: {order_items_table}\n")
    text = text.replace("table: products\n", f"table: {products_table}\n")
    text = text.replace("table: customers\n", f"table: {customers_table}\n")
    text = text.replace("warehouse: duckdb", f"warehouse: {warehouse}")

    output.write_text(text)
    console.print(f"[green]✓[/green] Retail pack written to [cyan]{output}[/cyan]")

    # Count and display the loaded rules for confirmation.
    from ..rules.parser import load_rules as _load_rules

    rules = _load_rules(output)
    console.print(
        f"[bold]{len(rules)}[/bold] rules covering: orders, order_items, products, customers"
    )


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port"),
    db: str = typer.Option(":memory:", "--db", help="DuckDB file path (or :memory:)"),
    warehouse: str = typer.Option("duckdb", "--warehouse", "-w", help="Warehouse: duckdb|postgres"),
    pg_dsn: str | None = typer.Option(None, "--pg-dsn", help="Postgres/Redshift DSN"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Disable LLM diagnosis"),
    llm: str = typer.Option("anthropic", "--llm", help="LLM provider: anthropic|openai|ollama"),
    llm_model: str | None = typer.Option(None, "--llm-model", help="Override model name"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev mode)"),
) -> None:
    """Start the Thota DQ REST API server."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn not installed. Run: pip install thota-dq[rest][/red]")
        raise typer.Exit(1)

    warehouse_adapter = _build_warehouse_adapter(
        warehouse,
        db,
        pg_dsn,
        "localhost",
        5432,
        "postgres",
        "postgres",
        "",
        "public",
    )
    llm_adapter = None if no_llm else _build_llm_adapter(llm, llm_model, "http://localhost:11434")

    from ..server.app import create_app

    api = create_app(warehouse_adapter=warehouse_adapter, llm_adapter=llm_adapter)

    console.print(f"[bold blue]Thota DQ API[/bold blue] → http://{host}:{port}/docs")
    uvicorn.run(api, host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
