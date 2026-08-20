"""
Tests for app/parser.py — verifies that a real .hl7 file is parsed correctly.
Uses the existing sample file in data/hl7/inbox/patient_001.hl7.
"""

import os
import pytest
from app.parser import parse_hl7_file

# Path to our known-good sample file
SAMPLE_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "hl7", "inbox", "patient_001.hl7"
)


@pytest.fixture(scope="module")
def parsed():
    """Parse the sample file once and reuse across all tests in this module."""
    pid_data, obx_data = parse_hl7_file(SAMPLE_FILE)
    return pid_data, obx_data


# ── PID fields ────────────────────────────────────────────────────────────────

def test_patient_id_extracted(parsed):
    pid, _ = parsed
    assert pid["patient_id"] == "PAT001"

def test_message_control_id_extracted(parsed):
    pid, _ = parsed
    assert pid["message_control_id"] == "MSG00001"

def test_family_name_extracted(parsed):
    pid, _ = parsed
    assert pid["family_name"] == "Smith"

def test_given_name_extracted(parsed):
    pid, _ = parsed
    assert pid["given_name"] == "John"

def test_middle_name_extracted(parsed):
    pid, _ = parsed
    assert pid["middle_name"] == "A"

def test_dob_extracted(parsed):
    pid, _ = parsed
    assert pid["dob"] == "19800315"

def test_gender_extracted(parsed):
    pid, _ = parsed
    assert pid["gender"] == "M"

def test_address_city_extracted(parsed):
    pid, _ = parsed
    assert pid["address"]["city"] == "Springfield"

def test_address_state_extracted(parsed):
    pid, _ = parsed
    assert pid["address"]["state"] == "IL"

def test_phone_extracted(parsed):
    pid, _ = parsed
    assert pid["phone"] == "555-123-4567"


# ── OBX fields ────────────────────────────────────────────────────────────────

def test_obx_count(parsed):
    _, obx_list = parsed
    assert len(obx_list) == 3

def test_first_obx_loinc_code(parsed):
    _, obx_list = parsed
    assert obx_list[0]["loinc_code"] == "8480-6"

def test_first_obx_description(parsed):
    _, obx_list = parsed
    assert obx_list[0]["description"] == "Systolic Blood Pressure"

def test_first_obx_value(parsed):
    _, obx_list = parsed
    assert obx_list[0]["value"] == "120"

def test_first_obx_unit(parsed):
    _, obx_list = parsed
    assert obx_list[0]["unit"] == "mm[Hg]"

def test_first_obx_status(parsed):
    _, obx_list = parsed
    assert obx_list[0]["status"] == "F"

def test_all_obx_have_loinc_codes(parsed):
    _, obx_list = parsed
    for obs in obx_list:
        assert obs["loinc_code"] != ""
