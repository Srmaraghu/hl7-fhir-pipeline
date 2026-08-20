"""
main.py

Entry point for the HL7 → FHIR pipeline.

What it does:
  1. Reads a .hl7 file from data/hl7/
  2. Parses PID → patient demographics
  3. Parses OBX → observation results
  4. Transforms both into FHIR R4 resources
  5. Prints the results as formatted JSON

Run:
  python -m app.main
"""

import json
import os

from app.parser import parse_hl7_file
from app.transformer import pid_to_fhir_patient, obx_list_to_fhir_observations

# Path to our sample HL7 message — relative to project root
HL7_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "hl7", "patient_admit.hl7"
)


def run():
    print("=" * 60)
    print("HL7 v2 → FHIR Pipeline")
    print("=" * 60)

    # Step 1: Parse — returns (pid_dict, obx_list)
    print(f"\n[1] Parsing HL7 file: {os.path.normpath(HL7_FILE)}")
    pid_data, obx_data = parse_hl7_file(HL7_FILE)

    print(f"\n    Found {len(obx_data)} OBX observation(s)")

    # Step 2: Transform PID → FHIR Patient
    print("\n[2] Transforming PID → FHIR R4 Patient...")
    fhir_patient = pid_to_fhir_patient(pid_data)
    print(json.dumps(fhir_patient, indent=2))

    # Step 3: Transform OBX list → FHIR Observations
    print("\n[3] Transforming OBX → FHIR R4 Observations...")
    fhir_observations = obx_list_to_fhir_observations(obx_data)

    for i, obs in enumerate(fhir_observations, start=1):
        print(f"\n    Observation {i}:")
        print(json.dumps(obs, indent=2))

    print("\n" + "=" * 60)
    print(f"Done. Produced 1 Patient + {len(fhir_observations)} Observation(s).")


if __name__ == "__main__":
    run()
