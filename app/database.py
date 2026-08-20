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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id                  TEXT        PRIMARY KEY,
                patient_id          TEXT        NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
                resource_type       TEXT        NOT NULL DEFAULT 'Observation',
                resource            JSONB       NOT NULL,
                -- pipeline-only dedup columns (not present in API schema, added safely)
                message_control_id  TEXT,
                loinc_code          TEXT,
                created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (patient_id, message_control_id, loinc_code)
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


def insert_patient(patient_id: str, fhir_patient: dict) -> str:
    """
    Insert a FHIR Patient resource using the shared schema.

    The patient's MR number (PID-3) is used as a stable lookup key via
    the resource JSONB, but the primary key is a UUID — matching how
    fhir-patient-api creates patients.

    Returns the UUID id assigned to this patient.
    """
    conn = get_connection()

    # check if a patient with this MR number already exists
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM patients
            WHERE resource->'identifier'->0->>'value' = %s
            """,
            (patient_id,)
        )
        row = cur.fetchone()

    if row:
        existing_id = row[0]
        print(f"[DB] Patient already exists (id={existing_id})")
        return existing_id

    # assign a new UUID as the FHIR logical id
    fhir_id = str(uuid.uuid4())
    fhir_patient["id"] = fhir_id

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO patients (id, resource_type, resource)
                VALUES (%s, 'Patient', %s)
                ON CONFLICT (id) DO NOTHING;
                """,
                (fhir_id, json.dumps(fhir_patient))
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    print(f"[DB] Patient inserted (id={fhir_id})")
    return fhir_id


def insert_observation(
    patient_fhir_id: str,
    message_control_id: str,
    loinc_code: str,
    description: str,
    fhir_obs: dict,
):
    """
    Insert a FHIR Observation resource using the shared schema.

    patient_fhir_id is the UUID returned by insert_patient() — the actual
    primary key in the patients table, not the MR number.
    """
    obs_id = str(uuid.uuid4())
    fhir_obs["id"] = obs_id

    # link observation back to patient using FHIR reference format
    fhir_obs["subject"] = {"reference": f"Patient/{patient_fhir_id}"}

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO observations
                    (id, patient_id, resource_type, resource, message_control_id, loinc_code)
                VALUES (%s, %s, 'Observation', %s, %s, %s)
                ON CONFLICT (patient_id, message_control_id, loinc_code) DO NOTHING;
                """,
                (obs_id, patient_fhir_id, json.dumps(fhir_obs), message_control_id, loinc_code)
            )
            if cur.rowcount == 1:
                print(f"[DB] Observation inserted: {loinc_code} ({description})")
            else:
                print(f"[DB] Observation skipped (already exists): {loinc_code} ({description})")
        conn.commit()
    except Exception:
        conn.rollback()
        raise


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
