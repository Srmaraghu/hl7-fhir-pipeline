import json
import os

import psycopg
from dotenv import load_dotenv

load_dotenv()

_conn = None


def get_connection():
    """Return a live psycopg2 connection, creating one if needed."""
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
    Create patients and observations tables if they don't exist yet.
    Called once at startup.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id          SERIAL PRIMARY KEY,
                patient_id  TEXT UNIQUE NOT NULL,   -- MR number from PID-3
                fhir_data   JSONB NOT NULL,          -- full FHIR Patient resource
                created_at  TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS observations (
                id          SERIAL PRIMARY KEY,
                patient_id  TEXT NOT NULL,           -- foreign key to patients.patient_id
                loinc_code  TEXT,                    -- OBX-3 code
                description TEXT,                    -- OBX-3 display name
                fhir_data   JSONB NOT NULL,          -- full FHIR Observation resource
                created_at  TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
            );
        """)
    conn.commit()
    print("[DB] Tables ready.")


def insert_patient(patient_id: str, fhir_patient: dict):
    """
    Insert a FHIR Patient resource into the patients table.
    Uses ON CONFLICT DO NOTHING so re-running the pipeline won't duplicate rows.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO patients (patient_id, fhir_data)
            VALUES (%s, %s)
            ON CONFLICT (patient_id) DO NOTHING;
            """,
            (patient_id, json.dumps(fhir_patient))
        )
    conn.commit()
    print(f"[DB] Patient inserted: {patient_id}")


def insert_observation(patient_id: str, loinc_code: str, description: str, fhir_obs: dict):
    """
    Insert a FHIR Observation resource into the observations table.
    """
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observations (patient_id, loinc_code, description, fhir_data)
            VALUES (%s, %s, %s, %s);
            """,
            (patient_id, loinc_code, description, json.dumps(fhir_obs))
        )
    conn.commit()
    print(f"[DB] Observation inserted: {loinc_code} ({description})")
