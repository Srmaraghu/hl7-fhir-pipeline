"""
Airflow DAG that orchestrates the HL7 → FHIR → PostgreSQL pipeline.
  setup_tables
       ↓
  ingest_hl7_files          ← reads inbox/, processes all .hl7 files
       ↓
  check_dead_letter          ← fails the DAG if too many bad messages
       ↓
  report_summary             ← prints final stats

Each task passes data to the next using XCom (Airflow's built-in
key-value store). For example, ingest_hl7_files pushes a summary dict,
and report_summary pulls it to print the results.
"""

from __future__ import annotations

import glob
import os
from datetime import timedelta

import pendulum

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator

# ── constants ─────────────────────────────────────────────────────────────────

# Path to the inbox folder — relative to the project root
INBOX = os.path.join(
    os.path.dirname(__file__), "..", "data", "hl7", "inbox"
)

# If more than this % of messages fail, fail the whole DAG run
DEAD_LETTER_THRESHOLD_PCT = 30


# ── task functions ────────────────────────────────────────────────────────────
# Each function below becomes one Airflow task.
# They receive **context so Airflow can inject the task instance (ti),
# which is used to push/pull XCom values between tasks.

def setup_db_tables(**context):
    """
    Task 1: Ensure all DB tables exist before processing starts.
    Idempotent — safe to run every time (uses CREATE TABLE IF NOT EXISTS).
    """
    from app.database import create_tables
    create_tables()
    print("[DAG] DB tables ready.")


def ingest_hl7_files(**context):
    """
    Task 2: Process all .hl7 files in the inbox directory.

    This is the core pipeline logic — parse → validate → transform → persist.
    Pushes a summary dict to XCom so downstream tasks can use the stats.

    XCom push: key="summary", value={"total": N, "valid": N, "invalid": N}
    """
    from app.parser import parse_hl7_file
    from app.transformer import (
        pid_to_fhir_patient,
        obx_list_to_fhir_observations,
        build_obs_payloads,
    )
    from app.validator import validate, extract_reason_code
    from app.database import persist_message, insert_dead_letter

    hl7_files = sorted(glob.glob(os.path.join(INBOX, "*.hl7")))

    if not hl7_files:
        print(f"[DAG] No .hl7 files found in {INBOX}")
        context["ti"].xcom_push(
            key="summary",
            value={"total": 0, "valid": 0, "invalid": 0},
        )
        return

    print(f"[DAG] Processing {len(hl7_files)} file(s)")

    total   = len(hl7_files)
    valid   = 0
    invalid = 0

    for filepath in hl7_files:
        filename = os.path.basename(filepath)
        try:
            pid_data, obx_data = parse_hl7_file(filepath)
            is_valid, full_reason = validate(pid_data, obx_data)

            if not is_valid:
                reason_code = extract_reason_code(full_reason)
                with open(filepath, "r") as f:
                    raw = f.read()
                insert_dead_letter(filename, reason_code, raw)
                print(f"  INVALID - {filename}: {full_reason}")
                invalid += 1
                continue

            fhir_patient      = pid_to_fhir_patient(pid_data)
            fhir_observations = obx_list_to_fhir_observations(obx_data)
            obs_payloads      = build_obs_payloads(obx_data, fhir_observations)

            patient_fhir_id = persist_message(
                mr_number=pid_data.get("patient_id", ""),
                fhir_patient=fhir_patient,
                message_control_id=pid_data.get("message_control_id", ""),
                observations=obs_payloads,
            )
            print(f"  VALID - {filename} → patient id={patient_fhir_id}")
            valid += 1

        except Exception as e:
            # only dead-letter parse/validation failures — let DB/transform
            # errors propagate so Airflow can retry the task
            from app.database import insert_dead_letter
            from app.parser import parse_hl7_file as _parse  # already imported above
            try:
                with open(filepath, "r") as f:
                    raw = f.read()
                insert_dead_letter(filename, "PARSE_ERROR", raw)
                print(f"  ERROR - {filename}: {e}")
                invalid += 1
            except Exception as inner:
                # dead-letter insert itself failed — re-raise original so
                # Airflow retries the whole task
                raise RuntimeError(
                    f"Failed to dead-letter {filename}: {inner}"
                ) from e

    summary = {"total": total, "valid": valid, "invalid": invalid}
    print(f"[DAG] Ingestion done: {summary}")

    # push summary to XCom so downstream tasks can read it
    context["ti"].xcom_push(key="summary", value=summary)


def check_dead_letter(**context):
    """
    Task 3: Quality gate — fail the DAG if too many messages failed.

    Pulls the summary from XCom (written by ingest_hl7_files).
    If invalid % exceeds DEAD_LETTER_THRESHOLD_PCT, raises an exception
    which causes Airflow to mark this DAG run as FAILED and trigger a retry.

    XCom pull: key="summary" from task "ingest_hl7_files"
    """
    # pull the summary dict that ingest_hl7_files pushed
    summary = context["ti"].xcom_pull(
        task_ids="ingest_hl7_files",
        key="summary",
    )

    if not summary:
        raise ValueError(
            "No summary found in XCom — ingest_hl7_files may not have run or failed "
            "before pushing stats. Check upstream task logs."
        )

    total   = summary.get("total", 0)
    invalid = summary.get("invalid", 0)

    if total == 0:
        print("[DAG] No messages processed — skipping dead letter check.")
        return

    failure_pct = (invalid / total) * 100
    print(f"[DAG] Dead letter check: {invalid}/{total} failed ({failure_pct:.1f}%)")

    if failure_pct > DEAD_LETTER_THRESHOLD_PCT:
        raise ValueError(
            f"Dead letter threshold exceeded: {failure_pct:.1f}% failed "
            f"(threshold={DEAD_LETTER_THRESHOLD_PCT}%). "
            f"Check the dead_letter table for details."
        )

    print(f"[DAG] Dead letter check passed.")


def report_summary(**context):
    """
    Task 4: Print the final pipeline summary.

    Pulls the summary from XCom and formats a clean report.
    In a production pipeline you'd send this to Slack or email instead.

    XCom pull: key="summary" from task "ingest_hl7_files"
    """
    summary = context["ti"].xcom_pull(
        task_ids="ingest_hl7_files",
        key="summary",
    )

    if not summary:
        print("[DAG] No summary available — upstream task may not have produced results.")
        return

    total   = summary.get("total", 0)
    valid   = summary.get("valid", 0)
    invalid = summary.get("invalid", 0)

    print("=" * 50)
    print("HL7 PIPELINE RUN SUMMARY")
    print("=" * 50)
    print(f"  Total processed : {total}")
    print(f"  Valid           : {valid}")
    print(f"  Invalid / Failed: {invalid}")
    print("=" * 50)


# ── DAG definition ────────────────────────────────────────────────────────────
# default_args apply to every task unless overridden.

default_args = {
    "owner":            "airflow",
    "retries":          2,                       # retry each task up to 2 times on failure
    "retry_delay":      timedelta(minutes=2),    # wait 2 min between retries
}

with DAG(
    dag_id="hl7_fhir_pipeline",
    description="HL7 v2 → FHIR → PostgreSQL ingestion pipeline",
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    schedule="@daily",
    catchup=False,
    default_args=default_args,
    tags=["healthcare", "hl7", "fhir"],
) as dag:

    # ── tasks ─────────────────────────────────────────────────────────────────

    t1_setup = PythonOperator(
        task_id="setup_db_tables",
        python_callable=setup_db_tables,
    )

    t2_ingest = PythonOperator(
        task_id="ingest_hl7_files",
        python_callable=ingest_hl7_files,
    )

    t3_check = PythonOperator(
        task_id="check_dead_letter",
        python_callable=check_dead_letter,
    )

    t4_report = PythonOperator(
        task_id="report_summary",
        python_callable=report_summary,
    )

    t5_dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="cd /opt/airflow/dbt/hl7_analytics && dbt run && dbt test",
        env={
            "DBT_PROFILES_DIR": "/opt/airflow/dbt/hl7_analytics",
            "DB_HOST": "db",
            "DB_PORT": "5432",
            "DB_NAME": "fhirdb",
            "DB_USER": "fhiruser",
            "DB_PASSWORD": "fhirpassword",
        },
    )

    # ── task order (>> means "then run") ──────────────────────────────────────
    t1_setup >> t2_ingest >> t3_check >> t5_dbt_run >> t4_report
