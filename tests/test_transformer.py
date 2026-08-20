"""
Tests for app/transformer.py — verifies FHIR output shape and field mappings.
No database or file I/O needed.
"""

import pytest
from app.transformer import (
    pid_to_fhir_patient,
    obx_to_fhir_observation,
    obx_list_to_fhir_observations,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def make_pid(**overrides) -> dict:
    base = {
        "patient_id":  "PAT001",
        "family_name": "Smith",
        "given_name":  "John",
        "middle_name": "A",
        "dob":         "19800315",
        "gender":      "M",
        "address": {
            "street":  "123 Main St",
            "city":    "Springfield",
            "state":   "IL",
            "zip":     "62701",
            "country": "USA",
        },
        "phone": "555-123-4567",
    }
    base.update(overrides)
    return base


def make_obx(**overrides) -> dict:
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


# ── pid_to_fhir_patient ───────────────────────────────────────────────────────

def test_resource_type_is_patient():
    result = pid_to_fhir_patient(make_pid())
    assert result["resourceType"] == "Patient"

def test_patient_identifier_value():
    result = pid_to_fhir_patient(make_pid(patient_id="PAT999"))
    assert result["identifier"][0]["value"] == "PAT999"

def test_patient_identifier_type_is_mr():
    result = pid_to_fhir_patient(make_pid())
    coding = result["identifier"][0]["type"]["coding"][0]
    assert coding["code"] == "MR"

def test_patient_name_family():
    result = pid_to_fhir_patient(make_pid(family_name="Jones"))
    assert result["name"][0]["family"] == "Jones"

def test_patient_name_given_includes_middle():
    result = pid_to_fhir_patient(make_pid(given_name="Mary", middle_name="B"))
    assert result["name"][0]["given"] == ["Mary", "B"]

def test_patient_name_given_no_middle():
    result = pid_to_fhir_patient(make_pid(given_name="Mary", middle_name=""))
    assert result["name"][0]["given"] == ["Mary"]

# Gender mapping
@pytest.mark.parametrize("hl7,fhir", [
    ("M", "male"),
    ("F", "female"),
    ("O", "other"),
    ("U", "unknown"),
    ("",  "unknown"),
    ("Z", "unknown"),   # unmapped code → unknown
])
def test_gender_mapping(hl7, fhir):
    result = pid_to_fhir_patient(make_pid(gender=hl7))
    assert result["gender"] == fhir

# DOB formatting
@pytest.mark.parametrize("hl7_dob,fhir_dob", [
    ("19800315", "1980-03-15"),
    ("20001231", "2000-12-31"),
    ("",         ""),
    ("bad",      ""),
])
def test_dob_formatting(hl7_dob, fhir_dob):
    result = pid_to_fhir_patient(make_pid(dob=hl7_dob))
    assert result["birthDate"] == fhir_dob

def test_address_fields():
    result = pid_to_fhir_patient(make_pid())
    addr = result["address"][0]
    assert addr["city"] == "Springfield"
    assert addr["state"] == "IL"
    assert addr["postalCode"] == "62701"
    assert addr["country"] == "USA"
    assert addr["line"] == ["123 Main St"]

def test_empty_address_returns_empty_list():
    pid = make_pid(address={"street": "", "city": "", "state": "", "zip": "", "country": ""})
    result = pid_to_fhir_patient(pid)
    assert result["address"] == []

def test_telecom_phone():
    result = pid_to_fhir_patient(make_pid(phone="555-999-0000"))
    assert result["telecom"][0]["value"] == "555-999-0000"
    assert result["telecom"][0]["system"] == "phone"

def test_empty_phone_returns_empty_telecom():
    result = pid_to_fhir_patient(make_pid(phone=""))
    assert result["telecom"] == []


# ── obx_to_fhir_observation ───────────────────────────────────────────────────

def test_resource_type_is_observation():
    result = obx_to_fhir_observation(make_obx())
    assert result["resourceType"] == "Observation"

def test_observation_status_final():
    result = obx_to_fhir_observation(make_obx(status="F"))
    assert result["status"] == "final"

@pytest.mark.parametrize("hl7_status,fhir_status", [
    ("F", "final"),
    ("P", "preliminary"),
    ("C", "amended"),
    ("X", "cancelled"),
    ("",  "unknown"),
])
def test_observation_status_mapping(hl7_status, fhir_status):
    result = obx_to_fhir_observation(make_obx(status=hl7_status))
    assert result["status"] == fhir_status

def test_observation_loinc_code():
    result = obx_to_fhir_observation(make_obx(loinc_code="2345-7"))
    assert result["code"]["coding"][0]["code"] == "2345-7"
    assert result["code"]["coding"][0]["system"] == "http://loinc.org"

def test_observation_description():
    result = obx_to_fhir_observation(make_obx(description="Glucose"))
    assert result["code"]["text"] == "Glucose"

def test_observation_numeric_value():
    result = obx_to_fhir_observation(make_obx(value="120"))
    assert result["valueQuantity"]["value"] == 120.0

def test_observation_non_numeric_value():
    result = obx_to_fhir_observation(make_obx(value="Positive"))
    assert result["valueQuantity"]["value"] == "Positive"

def test_observation_unit():
    result = obx_to_fhir_observation(make_obx(unit="mg/dL"))
    assert result["valueQuantity"]["unit"] == "mg/dL"

def test_observation_reference_range_present():
    result = obx_to_fhir_observation(make_obx(normal_range="70-100"))
    assert result["referenceRange"][0]["text"] == "70-100"

def test_observation_no_reference_range_when_empty():
    result = obx_to_fhir_observation(make_obx(normal_range=""))
    assert "referenceRange" not in result


# ── obx_list_to_fhir_observations ────────────────────────────────────────────

def test_obx_list_returns_correct_count():
    obx_list = [make_obx(loinc_code="8480-6"), make_obx(loinc_code="2345-7")]
    result = obx_list_to_fhir_observations(obx_list)
    assert len(result) == 2

def test_empty_obx_list_returns_empty():
    result = obx_list_to_fhir_observations([])
    assert result == []
