"""
Tests for app/validator.py — every rule, both the pass and fail case.
No database or file I/O needed here.
"""

import pytest
from app.validator import validate, extract_reason_code


# ── helpers ───────────────────────────────────────────────────────────────────

def make_pid(**overrides) -> dict:
    """Return a minimal valid PID dict, with optional field overrides."""
    base = {
        "patient_id":         "PAT001",
        "message_control_id": "MSG00001",
        "family_name":        "Smith",
        "given_name":         "John",
        "middle_name":        "A",
        "dob":                "19800315",
        "gender":             "M",
        "address": {
            "street": "123 Main St",
            "city":   "Springfield",
            "state":  "IL",
            "zip":    "62701",
            "country": "USA",
        },
        "phone": "555-123-4567",
    }
    base.update(overrides)
    return base


def make_obx(**overrides) -> dict:
    """Return a minimal valid OBX dict."""
    base = {
        "loinc_code":   "8480-6",
        "description":  "Systolic Blood Pressure",
        "value":        "120",
        "unit":         "mm[Hg]",
        "normal_range": "90-120",
        "status":       "F",
    }
    base.update(overrides)
    return base


# ── extract_reason_code ───────────────────────────────────────────────────────

def test_extract_reason_code_with_detail():
    assert extract_reason_code("MISSING_PATIENT_ID: PID-3 is empty") == "MISSING_PATIENT_ID"

def test_extract_reason_code_ok():
    assert extract_reason_code("OK") == "OK"

def test_extract_reason_code_no_colon():
    assert extract_reason_code("PARSE_ERROR") == "PARSE_ERROR"


# ── valid message passes all checks ──────────────────────────────────────────

def test_valid_message_passes():
    pid = make_pid()
    obx_list = [make_obx()]
    is_valid, reason = validate(pid, obx_list)
    assert is_valid is True
    assert reason == "OK"

def test_valid_message_no_obx_passes():
    """ADT messages without OBX segments are allowed."""
    pid = make_pid()
    is_valid, reason = validate(pid, [])
    assert is_valid is True


# ── MISSING_PATIENT_ID ────────────────────────────────────────────────────────

def test_missing_patient_id_fails():
    pid = make_pid(patient_id="")
    is_valid, reason = validate(pid, [])
    assert is_valid is False
    assert extract_reason_code(reason) == "MISSING_PATIENT_ID"

def test_whitespace_patient_id_fails():
    pid = make_pid(patient_id="   ")
    is_valid, reason = validate(pid, [])
    assert is_valid is False
    assert extract_reason_code(reason) == "MISSING_PATIENT_ID"


# ── MISSING_MESSAGE_CONTROL_ID ───────────────────────────────────────────────

def test_missing_message_control_id_fails():
    pid = make_pid(message_control_id="")
    is_valid, reason = validate(pid, [])
    assert is_valid is False
    assert extract_reason_code(reason) == "MISSING_MESSAGE_CONTROL_ID"


# ── MISSING_DOB / INVALID_DOB ─────────────────────────────────────────────────

def test_missing_dob_fails():
    pid = make_pid(dob="")
    is_valid, reason = validate(pid, [])
    assert is_valid is False
    assert extract_reason_code(reason) == "MISSING_DOB"

def test_invalid_dob_bad_month_fails():
    """Month 13 is not a real date."""
    pid = make_pid(dob="99991399")
    is_valid, reason = validate(pid, [])
    assert is_valid is False
    assert extract_reason_code(reason) == "INVALID_DOB"

def test_invalid_dob_future_fails():
    pid = make_pid(dob="20991231")
    is_valid, reason = validate(pid, [])
    assert is_valid is False
    assert extract_reason_code(reason) == "INVALID_DOB"

def test_invalid_dob_too_short_fails():
    pid = make_pid(dob="1980")
    is_valid, reason = validate(pid, [])
    assert is_valid is False
    assert extract_reason_code(reason) == "INVALID_DOB"

def test_invalid_dob_year_before_1900_fails():
    pid = make_pid(dob="18991231")
    is_valid, reason = validate(pid, [])
    assert is_valid is False
    assert extract_reason_code(reason) == "INVALID_DOB"

def test_valid_dob_passes():
    pid = make_pid(dob="19950601")
    is_valid, _ = validate(pid, [])
    assert is_valid is True


# ── INVALID_GENDER ────────────────────────────────────────────────────────────

def test_invalid_gender_fails():
    pid = make_pid(gender="X")
    is_valid, reason = validate(pid, [])
    assert is_valid is False
    assert extract_reason_code(reason) == "INVALID_GENDER"

def test_empty_gender_passes():
    """Empty gender is allowed — not all messages include it."""
    pid = make_pid(gender="")
    is_valid, _ = validate(pid, [])
    assert is_valid is True

@pytest.mark.parametrize("gender", ["M", "F", "O", "U", "A", "N", "C"])
def test_all_valid_gender_codes_pass(gender):
    pid = make_pid(gender=gender)
    is_valid, _ = validate(pid, [])
    assert is_valid is True


# ── MISSING_LOINC_CODE ────────────────────────────────────────────────────────

def test_missing_loinc_code_fails():
    pid = make_pid()
    obx_list = [make_obx(loinc_code="")]
    is_valid, reason = validate(pid, obx_list)
    assert is_valid is False
    assert extract_reason_code(reason) == "MISSING_LOINC_CODE"

def test_second_obx_missing_loinc_fails():
    """Only the second OBX is missing a LOINC code."""
    pid = make_pid()
    obx_list = [make_obx(loinc_code="8480-6"), make_obx(loinc_code="")]
    is_valid, reason = validate(pid, obx_list)
    assert is_valid is False
    assert extract_reason_code(reason) == "MISSING_LOINC_CODE"
    assert "OBX segment 2" in reason

def test_multiple_valid_obx_passes():
    pid = make_pid()
    obx_list = [make_obx(loinc_code="8480-6"), make_obx(loinc_code="2345-7")]
    is_valid, _ = validate(pid, obx_list)
    assert is_valid is True
