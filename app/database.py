"""
database.py

Handles PostgreSQL connection and insert operations for the pipeline.

Schema is deliberately aligned with fhir-patient-api/init.sql so that
data written by this pipeline can be read directly through the FHIR REST API:

  patients      → id TEXT PRIMARY KEY, resource JSONB
  observations  → id TEXT PRIMARY KEY, patient_id TEXT, resource JSONB
  dead_letter   → pipeline-only table for failed messages

This means: HL7 goes in through the pipeline, FHIR REST API serves it out.
"""

import json
import os
import uuid

import psycopg
from dotenv import load_dotenv

load_dotenv()

_conn = None


def get_connection():
    """Return a live psycopg connection, creating one if needed."""
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 5432)),
            dbname=os.getenv("DB_NAME", "fhirdb"),
            user=os.getenv("DB_USER", "fhiruser"),
            password=os.getenv("DB_PASSWORD", "fhirpassword"),
        )
    return _conn


def close_connection():
    """Close the connection if open."""
    global _conn
    if _conn and not _conn.closed:
        _conn.close()
        _conn = None


def create_tables():
    """
    Create tables using the same schema as fhir-patient-api so both projects
    share the same database. Also creates dead_letter for pipeline-only use.
    """
    conn = get_connection()
    with conn.cursor() as cur:

        # ── patients: matches fhir-patient-api/init.sql exactly ──────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id            TEXT        PRIMARY KEY,
                resource_type TEXT        NOT NULL DEFAULT 'Patient',
                resource      JSONB       NOT NULL,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_patients_resource
            ON patients USING GIN (resource);
        """)

        # ── observations: matches fhir-patient-api/init.sql exactly ──────────
        # obx_sequence (OBX-1) added to the conflict key so two observations
        # with the same LOINC in one message are stored as distinct rows.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id                  TEXT        PRIMARY KEY,
                patient_id          TEXT        NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                resource_type       TEXT        NOT NULL DEFAULT 'Observation',
                resource            JSONB       NOT NULL,
                -- pipeline-only dedup columns (not present in API schema, added safely)
                message_control_id  TEXT,
                loinc_code          TEXT,
                obx_sequence        TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (patient_id, message_control_id, obx_sequence)
            );
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_observations_patient_id
            ON observations (patient_id);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_observations_resource
            ON observations USING GIN (resource);
        """)

        # ── dead_letter: pipeline-only, not in fhir-patient-api ──────────────
        cur.execute("""
            CREATE TABLE IF NOT EXISTS dead_letter (
                id           SERIAL PRIMARY KEY,
                filename     TEXT NOT NULL,
                reason_code  TEXT NOT NULL,
                raw_message  TEXT,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            );
        """)

    conn.commit()
    print("[DB] Tables ready.")


def persist_message(
    mr_number: str,
    fhir_patient: dict,
    message_control_id: str,
    observations: list,
) -> str:
    """
    Persist a complete HL7 message — patient + all observations — in a single
    transaction. Either everything commits or nothing does.

    observations: list of dicts, each with keys:
        fhir_obs, loinc_code, obx_sequence, description

    Returns the patient's FHIR UUID.
    """
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # ── patient: look up or insert ────────────────────────────────────
            cur.execute(
                """
                SELECT id FROM patients
                WHERE resource->'identifier'->0->>'value' = %s
                """,
                (mr_number,)
            )
            row = cur.fetchone()

            if row:
                patient_fhir_id = row[0]
                print(f"[DB] Patient already exists (id={patient_fhir_id})")
            else:
                patient_fhir_id = str(uuid.uuid4())
                fhir_patient["id"] = patient_fhir_id
                cur.execute(
                    """
                    INSERT INTO patients (id, resource_type, resource)
                    VALUES (%s, 'Patient', %s)
                    ON CONFLICT (id) DO NOTHING;
                    """,
                    (patient_fhir_id, json.dumps(fhir_patient))
                )
                print(f"[DB] Patient inserted (id={patient_fhir_id})")

            # ── observations: all in the same transaction ─────────────────────
            for obs in observations:
                fhir_obs       = obs["fhir_obs"]
                loinc_code     = obs["loinc_code"]
                obx_sequence   = obs["obx_sequence"]
                description    = obs["description"]

                obs_id = str(uuid.uuid4())
                fhir_obs["id"] = obs_id
                fhir_obs["subject"] = {"reference": f"Patient/{patient_fhir_id}"}

                cur.execute(
                    """
                    INSERT INTO observations
                        (id, patient_id, resource_type, resource,
                         message_control_id, loinc_code, obx_sequence)
                    VALUES (%s, %s, 'Observation', %s, %s, %s, %s)
                    ON CONFLICT (patient_id, message_control_id, obx_sequence)
                    DO NOTHING;
                    """,
                    (
                        obs_id, patient_fhir_id, json.dumps(fhir_obs),
                        message_control_id, loinc_code, obx_sequence,
                    )
                )
                if cur.rowcount == 1:
                    print(f"[DB] Observation inserted: {loinc_code} ({description})")
                else:
                    print(f"[DB] Observation skipped (already exists): {loinc_code} ({description})")

        # single commit for the whole message
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    return patient_fhir_id


def insert_dead_letter(filename: str, reason_code: str, raw_message: str = ""):
    """Store a failed message with reason code."""
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dead_letter (filename, reason_code, raw_message)
            VALUES (%s, %s, %s);
            """,
            (filename, reason_code, raw_message)
        )
    conn.commit()
    print(f"[DB] Dead letter recorded: {filename} -> {reason_code}")
