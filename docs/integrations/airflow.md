# Airflow Integration

Aegis ships an `AegisOperator` that wraps an `aegis run` invocation as a native Airflow task. The operator runs in the Airflow worker process (no subprocess), uses the same audit trail as the CLI, and can push the run report to XCom.

---

## Install

```bash title="Terminal"
pip install "aegis-dq[airflow]"
```

---

## Basic usage

```python title="dags/daily_orders_dq.py"
from datetime import datetime
from airflow import DAG
from aegis.integrations.airflow import AegisOperator

with DAG(
    dag_id="daily_orders_dq",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
) as dag:

    validate_orders = AegisOperator(
        task_id="validate_orders",
        rules_file="/opt/airflow/dq/rules.yaml",
        warehouse="duckdb",
        db_path="/opt/airflow/data/warehouse.duckdb",
        no_llm=False,                        # set True to skip LLM
        llm="anthropic",                     # or "openai", "ollama"
        fail_on_severity=["critical"],        # only fail the task on critical
        output_xcom_key="dq_report",         # push JSON report to XCom
    )
```

---

## Operator parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `rules_file` | str | required | Path to `rules.yaml` |
| `warehouse` | str | `"duckdb"` | Warehouse adapter: `duckdb`, `bigquery`, `databricks`, `athena` |
| `db_path` | str | `None` | DuckDB file path (duckdb only) |
| `no_llm` | bool | `False` | Skip LLM diagnosis |
| `llm` | str | `"anthropic"` | LLM provider |
| `llm_model` | str | `None` | Override the default model |
| `fail_on_severity` | list | `["critical", "high"]` | Severity levels that cause the task to fail |
| `output_xcom_key` | str | `None` | XCom key to push the JSON report to |

---

## Reading the report downstream

```python title="dags/daily_orders_dq.py"
from airflow.operators.python import PythonOperator

def check_report(**context):
    report = context["ti"].xcom_pull(
        task_ids="validate_orders",
        key="dq_report",
    )
    failed = report["summary"]["failed"]
    print(f"DQ check: {failed} rule(s) failed")

read_report = PythonOperator(
    task_id="read_dq_report",
    python_callable=check_report,
)

validate_orders >> read_report
```

---

## Environment variables

Set your LLM API key as an Airflow Variable or in the worker environment:

```bash title="Terminal"
export ANTHROPIC_API_KEY=sk-ant-...
# or
export OPENAI_API_KEY=sk-...
```

For BigQuery, set `GOOGLE_APPLICATION_CREDENTIALS` to your service account JSON path.

!!! tip "Store secrets in Airflow's Secrets Backend"
    Avoid hardcoding API keys in DAG files or worker environment files. Use Airflow's built-in secrets backend (AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager) or Airflow Variables with encryption enabled. Retrieve them at runtime with `Variable.get("ANTHROPIC_API_KEY")` and pass as environment variables in your Airflow worker configuration.
