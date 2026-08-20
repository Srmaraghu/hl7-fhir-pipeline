"""
parser.py

Reads a raw HL7 v2 message file and extracts the PID and OBX segment fields
we care about for FHIR transformation.

Uses hl7apy.parser.parse_message() — the correct top-level entry point.
Returns plain Python dicts/lists of patient and observation fields.
"""

from typing import List
from hl7apy.parser import parse_message
from hl7apy.consts import VALIDATION_LEVEL


def parse_hl7_file(filepath: str) -> tuple:
    """
    Read an .hl7 file and return a tuple of (pid_dict, obx_list).

    pid_dict: patient demographics from PID segment
    obx_list: list of observation dicts from OBX segments
    """
    with open(filepath, "r") as f:
        raw = f.read().strip()

    # HL7 v2 uses \r as the segment terminator (not \n).
    # Text editors save files with \n, so we normalise here.
    raw = raw.replace("\r\n", "\r").replace("\n", "\r")

    # Use QUIET validation so unknown fields don't raise errors
    msg = parse_message(raw, validation_level=VALIDATION_LEVEL.QUIET)

    # MSH-10: message control ID — unique ID for this message, used for deduplication
    message_control_id = _safe(lambda: msg.msh.msh_10.value)

    pid_data = _parse_pid(msg)
    pid_data["message_control_id"] = message_control_id

    obx_data = parse_obx_segments(msg)

    return pid_data, obx_data


def _parse_pid(msg) -> dict:
    """Extract PID segment fields from a parsed message."""
    pid = msg.pid

    # PID-3: patient identifier — first component (ID value)
    patient_id  = _safe(lambda: pid.pid_3.cx_1.value)

    # PID-5: patient name
    family_name = _safe(lambda: pid.pid_5.xpn_1.value)
    given_name  = _safe(lambda: pid.pid_5.xpn_2.value)
    middle_name = _safe(lambda: pid.pid_5.xpn_3.value)

    # PID-7: date of birth
    dob         = _safe(lambda: pid.pid_7.ts_1.value)

    # PID-8: administrative sex
    gender      = _safe(lambda: pid.pid_8.value)

    # PID-11: address
    address = {
        "street":  _safe(lambda: pid.pid_11.xad_1.value),
        "city":    _safe(lambda: pid.pid_11.xad_3.value),
        "state":   _safe(lambda: pid.pid_11.xad_4.value),
        "zip":     _safe(lambda: pid.pid_11.xad_5.value),
        "country": _safe(lambda: pid.pid_11.xad_6.value),
    }

    # PID-13: phone
    phone = _safe(lambda: pid.pid_13.value)

    return {
        "patient_id":  patient_id,
        "family_name": family_name,
        "given_name":  given_name,
        "middle_name": middle_name,
        "dob":         dob,
        "gender":      gender,
        "address":     address,
        "phone":       phone,
    }


def parse_obx_segments(msg) -> List[dict]:
    """
    Extract all OBX segments from an already-parsed hl7apy message object.
    Returns a list of dicts, one per observation.
    """
    observations = []

    # msg.children gives us every segment in the message
    for segment in msg.children:
        if segment.name == "OBX":
            obs = {
                # OBX-2: value type (NM = numeric, ST = string, etc.)
                "value_type":   _safe(lambda s=segment: s.obx_2.value),

                # OBX-3: what was measured — LOINC code and display name
                "loinc_code":   _safe(lambda s=segment: s.obx_3.ce_1.value),
                "description":  _safe(lambda s=segment: s.obx_3.ce_2.value),

                # OBX-5: the actual result value (e.g. 120)
                "value":        _safe(lambda s=segment: s.obx_5.value),

                # OBX-6: units (e.g. mm[Hg], mg/dL)
                "unit":         _safe(lambda s=segment: s.obx_6.ce_1.value),

                # OBX-7: normal reference range (e.g. 90-120)
                "normal_range": _safe(lambda s=segment: s.obx_7.value),

                # OBX-11: observation status (F = Final)
                "status":       _safe(lambda s=segment: s.obx_11.value),
            }
            observations.append(obs)

    return observations


def _safe(fn) -> str:
    """Call fn(), return '' on any exception."""
    try:
        result = fn()
        return result if result is not None else ""
    except Exception:
        return ""
