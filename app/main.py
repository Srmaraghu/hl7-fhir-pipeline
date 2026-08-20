"""
main.py

Entry point for the HL7 → FHIR pipeline.

What it does:
  1. Loops over every .hl7 file in data/hl7/inbox/
  2. Parses PID + OBX segments from each file
  3. Validates the parsed data
  4. Valid   → transform to FHIR → save to PostgreSQL
  5. Invalid → save to dead_letter table with reason code only (not full message)
  6. Prints a summary report at the end

Run:
  python -m app.main
"""

import glob
import os

from app.parser import parse_hl7_file
from app.transformer import pid_to_fhir_patient, obx_list_to_fhir_observations
from app.validator import validate, extract_reason_code
from app.database import (
    create_tables,
    insert_patient,
    insert_observation,
    insert_dead_letter,
    close_connection,
)

INBOX = os.path.join(os.path.dirname(__file__), "..", "data", "hl7", "inbox")


def run():
    print("=" * 60)
    print("HL7 v2 → FHIR Pipeline")
    print("=" * 60)

    hl7_files = sorted(glob.glob(os.path.join(INBOX, "*.hl7")))

    if not hl7_files:
        print(f"\nNo .hl7 files found in {INBOX}")
        return

    print(f"\nFound {len(hl7_files)} file(s) in inbox\n")

    create_tables()

    total   = len(hl7_files)
    valid   = 0
    invalid = 0
    errors  = []   # list of (filename, reason_code, full_reason)

    for filepath in hl7_files:
        filename = os.path.basename(filepath)
        print(f"{'─' * 40}")
        print(f"Processing: {filename}")

        try:
            # Step 1: parse
            pid_data, obx_data = parse_hl7_file(filepath)

            # Step 2: validate
            is_valid, full_reason = validate(pid_data, obx_data)

            if not is_valid:
                # split "REASON_CODE: detail" → store only the code in DB
                reason_code = extract_reason_code(full_reason)

                with open(filepath, "r") as f:
                    raw = f.read()

                insert_dead_letter(filename, reason_code, raw)
                print(f"  INVALID - {full_reason}")
                invalid += 1
                errors.append((filename, reason_code, full_reason))
                continue

            # Step 3: transform
            fhir_patient      = pid_to_fhir_patient(pid_data)
            fhir_observations = obx_list_to_fhir_observations(obx_data)

            # Step 4: save to DB
            patient_id         = pid_data.get("patient_id", "")
            message_control_id = pid_data.get("message_control_id", "")
            insert_patient(patient_id, fhir_patient)

            for obs, fhir_obs in zip(obx_data, fhir_observations):
                insert_observation(
                    patient_id=patient_id,
                    message_control_id=message_control_id,
                    loinc_code=obs.get("loinc_code", ""),
                    description=obs.get("description", ""),
                    fhir_obs=fhir_obs,
                )

            print(f"  VALID - patient {patient_id}, {len(fhir_observations)} observation(s) saved")
            valid += 1

        except Exception as e:
            # unexpected crash — isolate so one bad file doesn't kill the run
            reason_code = "PARSE_ERROR"
            full_reason = f"PARSE_ERROR: {str(e)}"
            try:
                with open(filepath, "r") as f:
                    raw = f.read()
                insert_dead_letter(filename, reason_code, raw)
            except Exception:
                pass
            print(f"  ERROR - {full_reason}")
            invalid += 1
            errors.append((filename, reason_code, full_reason))

    # ── summary report ────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("PIPELINE SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Total processed : {total}")
    print(f"  Valid           : {valid}")
    print(f"  Invalid / Failed: {invalid}")

    if errors:
        print(f"\n  Failed files:")
        for filename, reason_code, full_reason in errors:
            print(f"    {filename}")
            print(f"      [{reason_code}] {full_reason.split(':', 1)[-1].strip()}")

    print(f"{'=' * 60}")

    close_connection()


if __name__ == "__main__":
    run()
