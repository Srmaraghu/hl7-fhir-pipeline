"""
main.py

Entry point for the HL7 → FHIR pipeline.

What it does:
  1. Reads a .hl7 file from data/hl7/
  2. Parses PID → patient demographics
  3. Parses OBX → observation results
  4. Transforms both into FHIR R4 resources
  5. Saves everything to PostgreSQL

Run:
  python -m app.main
"""

import json
import os

from app.parser import parse_hl7_file
from app.transformer import pid_to_fhir_patient, obx_list_to_fhir_observations
from app.database import create_tables, insert_patient, insert_observation, close_connection

# Path to our sample HL7 message — relative to project root
HL7_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "hl7", "patient_admit.hl7"
)


def run():
    print("=" * 60)
    print("HL7 v2 → FHIR Pipeline")
    print("=" * 60)

    # Step 1: Parse
    print(f"\n[1] Parsing HL7 file: {os.path.normpath(HL7_FILE)}")
    pid_data, obx_data = parse_hl7_file(HL7_FILE)
    print(f"    Found {len(obx_data)} OBX observation(s)")

    # Step 2: Transform
    print("\n[2] Transforming to FHIR resources...")
    fhir_patient = pid_to_fhir_patient(pid_data)
    fhir_observations = obx_list_to_fhir_observations(obx_data)

    print("\n    FHIR Patient:")
    print(json.dumps(fhir_patient, indent=2))

    for i, obs in enumerate(fhir_observations, start=1):
        print(f"\n    Observation {i}:")
        print(json.dumps(obs, indent=2))

    # Step 3: Save to PostgreSQL
    print("\n[3] Saving to PostgreSQL...")
    create_tables()

    patient_id = pid_data.get("patient_id", "")
    insert_patient(patient_id, fhir_patient)

    for obs, fhir_obs in zip(obx_data, fhir_observations):
        insert_observation(
            patient_id=patient_id,
            loinc_code=obs.get("loinc_code", ""),
            description=obs.get("description", ""),
            fhir_obs=fhir_obs,
        )

    close_connection()

    print("\n" + "=" * 60)
    print(f"Done. Saved 1 Patient + {len(fhir_observations)} Observation(s) to DB.")


if __name__ == "__main__":
    run()
