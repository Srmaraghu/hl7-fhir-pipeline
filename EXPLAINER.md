# What Just Happened — Explained Like You're in 10th Grade

---

## The Big Picture (Why We Did This)

Hospitals in the US send patient information to each other every day.
When a patient gets admitted, their information needs to travel from one
computer system to another — maybe from the front desk to the lab, or
from one hospital to another.

The problem is: **different hospital systems speak different "languages".**

There are two main formats:

| Format | What it is | Who uses it |
|--------|-----------|-------------|
| **HL7 v2** | An old format from the 1980s. Still used by most hospitals today. | Old hospital systems |
| **FHIR** | A modern format. Looks like JSON. Used by new apps and APIs. | Modern systems, apps |

Since most hospitals still **send** data in HL7 v2 but modern systems **want** FHIR,
someone has to translate between the two.

**That's exactly what this pipeline does.**

```
Old hospital sends HL7 message
          ↓
Our pipeline reads and translates it
          ↓
Output is a clean FHIR Patient (JSON)
```

---

## Step 1 — What is an HL7 Message?

Open `data/hl7/patient_admit.hl7`. It looks like this:

```
MSH|^~\&|SENDING_APP|SENDING_FACILITY|...
EVN|A01|20240819120000
PID|1||PAT001^^^HOSPITAL^MR||Smith^John^A||19800315|M|||123 Main St...
PV1|1|I|ICU^101^A|||DR456^Jones^Mary...
```

This looks like gibberish. But it has a very strict structure.

### Each line is called a **segment**. Think of it like a row in a spreadsheet.

| Segment | What it means |
|---------|--------------|
| `MSH` | Message Header — "who sent this, when, what version" |
| `EVN` | Event — "what happened? (patient admitted)" |
| `PID` | Patient ID — **the patient's personal information** |
| `PV1` | Patient Visit — "which room, which doctor" |

### Each segment is split by the `|` character (the pipe symbol).

So `PID|1||PAT001^^^HOSPITAL^MR||Smith^John^A||19800315|M|...`

means:
- field 1 = `1` (set ID)
- field 2 = empty
- field 3 = `PAT001^^^HOSPITAL^MR` (patient ID)
- field 4 = empty
- field 5 = `Smith^John^A` (name — split further by `^`)
- field 7 = `19800315` (date of birth)
- field 8 = `M` (gender: Male)
- field 11 = `123 Main St^^Springfield^IL^62701^USA` (address)
- field 13 = `555-123-4567` (phone)

The `^` character splits a field into **sub-fields** (components).
So `Smith^John^A` means: family=Smith, given=John, middle=A.

---

## Step 2 — What is FHIR?

FHIR (Fast Healthcare Interoperability Resources) is a modern standard.
It uses **JSON** — the same format that web APIs use.

A FHIR Patient looks like this:

```json
{
  "resourceType": "Patient",
  "identifier": [{ "value": "PAT001" }],
  "name": [{ "family": "Smith", "given": ["John", "A"] }],
  "gender": "male",
  "birthDate": "1980-03-15"
}
```

Clean. Readable. Any modern system can understand it.

---

## Step 3 — The Three Files We Built

### 📄 `data/hl7/patient_admit.hl7` — The Input

This is a **fake but realistic** HL7 message we created.
It represents a patient named John Smith being admitted to the ICU.

In the real world, a hospital system would generate this file.
We made it by hand so we have something to test with.

---

### 📄 `app/parser.py` — The Reader

**Job: Read the HL7 file. Pull out the patient info. Give it back as a simple Python dict.**

```python
from hl7apy.parser import parse_message
from hl7apy.consts import VALIDATION_LEVEL
```
We import `hl7apy` — a Python library that knows how to read HL7 messages.
Think of it like a specialized dictionary that knows what `PID-5` means.

```python
with open(filepath, "r") as f:
    raw = f.read().strip()
```
Open the `.hl7` file and read it as plain text. `.strip()` removes
any extra blank lines at the start or end.

```python
raw = raw.replace("\r\n", "\r").replace("\n", "\r")
```
This is a quirky HL7 rule: the official spec says each segment must
end with `\r` (a carriage return — an old typewriter concept).
But when we saved the file on a Mac/Linux, it used `\n` (newline) instead.
This line converts `\n` → `\r` so hl7apy doesn't get confused.
**This was the bug that crashed the app the first time.**

```python
msg = parse_message(raw, validation_level=VALIDATION_LEVEL.QUIET)
```
Hand the raw text to hl7apy. It reads it and builds a Python object
we can navigate. `VALIDATION_LEVEL.QUIET` means "don't crash if
something looks slightly wrong — just do your best."

```python
pid = msg.pid
```
From the whole message, grab just the PID segment (the patient info row).

```python
patient_id = _safe(lambda: pid.pid_3.cx_1.value)
```
Navigate into `pid_3` (field 3) → `cx_1` (first sub-component) → `.value`.
This gives us `PAT001`.

The `_safe(lambda: ...)` wrapper just means: "try this, and if anything
goes wrong (field is missing, empty, etc.), just return an empty string
instead of crashing."

We do the same thing for name, DOB, gender, address, and phone.

At the end we return a plain Python dict:
```python
return {
    "patient_id": "PAT001",
    "family_name": "Smith",
    "given_name": "John",
    ...
}
```

---

### 📄 `app/transformer.py` — The Translator

**Job: Take the Python dict from parser.py. Build a FHIR Patient JSON out of it.**

```python
_GENDER_MAP = {
    "M": "male",
    "F": "female",
    "O": "other",
    "U": "unknown",
}
```
HL7 uses single letters for gender (`M`, `F`).
FHIR wants full words (`"male"`, `"female"`).
This dictionary is our translation table.

```python
def pid_to_fhir_patient(pid: dict) -> dict:
```
Takes the dict from parser.py and returns a new dict shaped like a FHIR Patient.

```python
"resourceType": "Patient",
```
Every FHIR resource must declare what type it is. This tells any FHIR
system "hey, this is a Patient record."

```python
"identifier": [{ "value": pid.get("patient_id", "") }]
```
The patient's MR number (PAT001) goes here. The extra `"type"` and
`"system"` fields around it are FHIR's way of saying "this ID is
specifically a Medical Record Number from this coding system."

```python
"birthDate": _format_dob(pid.get("dob", ""))
```
HL7 stores dates as `19800315` (no dashes).
FHIR wants `1980-03-15` (with dashes).
`_format_dob()` does that conversion using Python's `datetime.strptime`.

```python
"gender": _map_gender(pid.get("gender", ""))
```
Runs the gender through our `_GENDER_MAP` table. `"M"` becomes `"male"`.

```python
"address": _build_address(pid.get("address", {}))
```
Takes the address dict (street, city, state, zip, country) and wraps it
in the format FHIR expects — with keys like `"postalCode"` instead of `"zip"`.

```python
"telecom": _build_telecom(pid.get("phone", ""))
```
FHIR calls phone/email/fax etc. "telecom" (short for telecommunications).
We wrap the phone number with `"system": "phone"` and `"use": "home"`.

---

### 📄 `app/main.py` — The Boss

**Job: Run everything in order and print the results.**

```python
from app.parser import parse_hl7_file
from app.transformer import pid_to_fhir_patient
```
Import our two functions.

```python
HL7_FILE = os.path.join(
    os.path.dirname(__file__), "..", "data", "hl7", "patient_admit.hl7"
)
```
Build the file path to our `.hl7` file. `os.path.dirname(__file__)` means
"the folder where main.py lives" — then go up one level (`..`) and into
`data/hl7/`. This works no matter where on your computer the project lives.

```python
pid_data = parse_hl7_file(HL7_FILE)
```
Step 1: parse the HL7 file. Get back the dict.

```python
fhir_patient = pid_to_fhir_patient(pid_data)
```
Step 2: transform the dict into a FHIR Patient.

```python
print(json.dumps(fhir_patient, indent=2))
```
Step 3: print it as pretty JSON. `indent=2` adds the spaces so it's
readable instead of one giant line.

---

## The Full Flow in One Picture

```
patient_admit.hl7
        │
        │  (raw HL7 text with pipes and carets)
        ▼
   parser.py
        │  hl7apy reads the segments
        │  we extract PID fields
        │  return a simple Python dict
        ▼
  transformer.py
        │  rename fields to FHIR names
        │  convert date format
        │  convert gender code
        │  wrap in FHIR structure
        ▼
  FHIR Patient JSON
        │
        ▼
   printed to screen
   (later: saved to PostgreSQL)
```

---

## Why This Matters for Your Career

The reason you're building this:

> Most hospitals in the US **still send HL7 v2 messages**.
> Most modern systems (apps, APIs, cloud platforms) **want FHIR**.
> The person who can bridge that gap is a **healthcare data engineer**.

What you just built — even this tiny version — is the core of what
companies like Epic, Cerner, and healthcare startups pay engineers to build.

The next steps (OBX → FHIR Observation, then RabbitMQ, then PostgreSQL)
will make this look like a real production pipeline.
