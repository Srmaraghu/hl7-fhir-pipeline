"""
transformer.py

Takes parsed PID and OBX dicts from parser.py and builds FHIR R4 resources.

We build everything as plain Python dicts (JSON-serializable FHIR).

HL7 v2 → FHIR R4 mappings:

  PID-3  (MR number)   → Patient.identifier
  PID-5  (name)        → Patient.name
  PID-7  (DOB)         → Patient.birthDate
  PID-8  (gender)      → Patient.gender
  PID-11 (address)     → Patient.address
  PID-13 (phone)       → Patient.telecom

  OBX-3  (LOINC code)  → Observation.code
  OBX-5  (value)       → Observation.valueQuantity.value
  OBX-6  (unit)        → Observation.valueQuantity.unit
  OBX-7  (ref range)   → Observation.referenceRange
  OBX-11 (status)      → Observation.status
"""

from typing import List
from datetime import datetime


# HL7 administrative sex code → FHIR gender
_GENDER_MAP = {
    "M": "male",
    "F": "female",
    "O": "other",
    "U": "unknown",
}

# HL7 OBX-11 observation status → FHIR Observation.status
_STATUS_MAP = {
    "F": "final",
    "P": "preliminary",
    "C": "amended",
    "X": "cancelled",
}


def pid_to_fhir_patient(pid: dict) -> dict:
    """
    Transform a parsed PID dict into a FHIR R4 Patient resource.
    """
    patient = {
        "resourceType": "Patient",

        # Identifier — maps PID-3 MR number
        "identifier": [
            {
                "use": "usual",
                "type": {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                            "code":   "MR",
                            "display": "Medical Record Number",
                        }
                    ]
                },
                "value": pid.get("patient_id", ""),
            }
        ],

        # Name — maps PID-5
        "name": [
            {
                "use":    "official",
                "family": pid.get("family_name", ""),
                "given":  _build_given_names(pid),
            }
        ],

        # Gender — maps PID-8
        "gender": _map_gender(pid.get("gender", "")),

        # Birth date — maps PID-7 (YYYYMMDD → YYYY-MM-DD)
        "birthDate": _format_dob(pid.get("dob", "")),

        # Address — maps PID-11
        "address": _build_address(pid.get("address", {})),

        # Telecom (phone) — maps PID-13
        "telecom": _build_telecom(pid.get("phone", "")),
    }

    return patient


def obx_to_fhir_observation(obs: dict) -> dict:
    """
    Transform a single parsed OBX dict into a FHIR R4 Observation resource.

    Args:
        obs: one item from the list returned by parser.parse_obx_segments()

    Returns:
        A dict representing a FHIR R4 Observation resource.
    """
    observation = {
        "resourceType": "Observation",

        # OBX-11 status: "F" → "final"
        "status": _STATUS_MAP.get(obs.get("status", "").upper(), "unknown"),

        # OBX-3: what was measured — LOINC code + display name
        "code": {
            "coding": [
                {
                    "system":  "http://loinc.org",
                    "code":    obs.get("loinc_code", ""),
                    "display": obs.get("description", ""),
                }
            ],
            "text": obs.get("description", ""),
        },

        # OBX-5 + OBX-6: the result value and its units
        "valueQuantity": {
            "value": _parse_numeric(obs.get("value", "")),
            "unit":  obs.get("unit", ""),
        },
    }

    # OBX-7: normal reference range (only add if present)
    if obs.get("normal_range"):
        observation["referenceRange"] = [
            {"text": obs["normal_range"]}
        ]

    return observation


def obx_list_to_fhir_observations(obx_list: List[dict]) -> List[dict]:
    """
    Transform a list of OBX dicts into a list of FHIR Observation resources.
    """
    return [obx_to_fhir_observation(obs) for obs in obx_list]


def build_obs_payloads(obx_data: List[dict], fhir_observations: List[dict]) -> List[dict]:
    """
    Pair parsed OBX dicts with their FHIR Observation dicts into the payload
    format expected by database.persist_message().

    Uses strict=True so a length mismatch raises immediately rather than
    silently dropping observations.
    """
    return [
        {
            "fhir_obs":     fhir_obs,
            "loinc_code":   obs.get("loinc_code", ""),
            "obx_sequence": obs.get("obx_sequence", str(i + 1)),
            "description":  obs.get("description", ""),
        }
        for i, (obs, fhir_obs) in enumerate(zip(obx_data, fhir_observations, strict=True))
    ]


# ── helpers ──────────────────────────────────────────────────────────────────

def _build_given_names(pid: dict) -> list:
    """Collect given + middle name into FHIR given array."""
    names = []
    if pid.get("given_name"):
        names.append(pid["given_name"])
    if pid.get("middle_name"):
        names.append(pid["middle_name"])
    return names


def _map_gender(hl7_gender: str) -> str:
    """Convert HL7 PID-8 code to FHIR gender string."""
    return _GENDER_MAP.get(hl7_gender.upper(), "unknown")


def _format_dob(hl7_dob: str) -> str:
    """Convert HL7 date YYYYMMDD to FHIR date YYYY-MM-DD."""
    hl7_dob = hl7_dob.strip()
    if len(hl7_dob) >= 8:
        try:
            dt = datetime.strptime(hl7_dob[:8], "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return ""


def _build_address(addr: dict) -> list:
    """Build FHIR address array from PID-11 components."""
    if not any(addr.values()):
        return []
    return [
        {
            "use":        "home",
            "line":       [addr.get("street", "")] if addr.get("street") else [],
            "city":       addr.get("city", ""),
            "state":      addr.get("state", ""),
            "postalCode": addr.get("zip", ""),
            "country":    addr.get("country", ""),
        }
    ]


def _build_telecom(phone: str) -> list:
    """Build FHIR telecom array from PID-13 phone."""
    if not phone:
        return []
    return [
        {
            "system": "phone",
            "value":  phone,
            "use":    "home",
        }
    ]


def _parse_numeric(value: str):
    """Try to convert a string value to float. Return as-is if not numeric."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return value
