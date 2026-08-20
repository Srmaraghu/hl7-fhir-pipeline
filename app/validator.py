"""
Vaidates parsed PID and OBX data before we attempt any FHIR transformation
or database insert.
Each check returns a tuple: (is_valid: bool, reason_code: str)
Reason codes (stored in dead_letter table):
    MISSING_PATIENT_ID   — PID-3 is empty
    INVALID_DOB          — PID-7 is not a real date or is in the future
    INVALID_GENDER       — PID-8 is not a recognised HL7 gender code
    MISSING_LOINC_CODE   — one or more OBX segments have no LOINC code
"""

from datetime import datetime
from typing import List


# Valid HL7 administrative sex codes
VALID_GENDER_CODES = {"M", "F", "O", "U", "A", "N", "C"}


def validate(pid: dict, obx_list: List[dict]) -> tuple:
    """
    Run all checks against a parsed PID dict and OBX list.

    Returns:
        (True, "OK")                        if everything passes
        (False, "REASON_CODE: description") on first failure
    """
    checks = [
        _check_patient_id,
        _check_dob,
        _check_gender,
    ]

    # Run PID checks
    for check in checks:
        is_valid, reason = check(pid)
        if not is_valid:
            return False, reason

    # Run OBX checks
    is_valid, reason = _check_loinc_codes(obx_list)
    if not is_valid:
        return False, reason

    return True, "OK"


# ── individual checks ─────────────────────────────────────────────────────────

def _check_patient_id(pid: dict) -> tuple:
    """PID-3 must not be empty."""
    if not pid.get("patient_id", "").strip():
        return False, "MISSING_PATIENT_ID: PID-3 is empty"
    return True, "OK"


def _check_dob(pid: dict) -> tuple:
    """
    PID-7 must be a real date in YYYYMMDD format.
    Also rejects dates in the future and clearly wrong dates (year < 1900).
    """
    dob = pid.get("dob", "").strip()

    if not dob:
        return False, "MISSING_DOB: PID-7 is empty"

    # Must be at least 8 characters (YYYYMMDD)
    if len(dob) < 8:
        return False, f"INVALID_DOB: too short — got '{dob}'"

    try:
        dt = datetime.strptime(dob[:8], "%Y%m%d")
    except ValueError:
        return False, f"INVALID_DOB: '{dob}' is not a real date"

    # Reject future dates
    if dt > datetime.now():
        return False, f"INVALID_DOB: '{dob}' is in the future"

    # Reject implausible years
    if dt.year < 1900:
        return False, f"INVALID_DOB: year {dt.year} is implausible"

    return True, "OK"


def _check_gender(pid: dict) -> tuple:
    """PID-8 must be a recognised HL7 gender code (or empty is acceptable)."""
    gender = pid.get("gender", "").strip().upper()

    # Empty gender is a warning but we allow it through
    if not gender:
        return True, "OK"

    if gender not in VALID_GENDER_CODES:
        return False, f"INVALID_GENDER: '{gender}' is not a valid HL7 gender code"

    return True, "OK"


def _check_loinc_codes(obx_list: List[dict]) -> tuple:
    """
    Every OBX segment must have a non-empty LOINC code.
    If there are no OBX segments at all, we allow it through
    (some ADT messages have no observations).
    """
    if not obx_list:
        return True, "OK"

    for i, obs in enumerate(obx_list, start=1):
        if not obs.get("loinc_code", "").strip():
            return False, f"MISSING_LOINC_CODE: OBX segment {i} has no LOINC code"

    return True, "OK"
