# HL7 → FHIR Pipeline

A healthcare data pipeline that ingests HL7 v2 messages, parses them, and transforms them into FHIR R4 resources.

## Architecture

```
.hl7 files
    │
    ▼
parser.py       ← extracts PID segment fields
    │
    ▼
transformer.py  ← maps PID → FHIR R4 Patient resource
    │
    ▼
stdout (JSON)   ← Phase 1 output
```

## Project Structure

```
hl7-fhir-pipeline/
│
├── data/
│   └── hl7/
│       └── patient_admit.hl7   ← sample ADT A01 message
│
├── app/
│   ├── __init__.py
│   ├── parser.py               ← HL7 v2 parser (uses hl7apy)
│   ├── transformer.py          ← PID → FHIR Patient transformer
│   └── main.py                 ← entry point
│
├── tests/
├── requirements.txt
└── README.md
```

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python -m app.main
```

## HL7 → FHIR Field Mapping

| HL7 Segment | Field | FHIR Resource       | Element                  |
|-------------|-------|---------------------|--------------------------|
| PID-3       | MR #  | Patient.identifier  | value (type: MR)         |
| PID-5       | Name  | Patient.name        | family, given            |
| PID-7       | DOB   | Patient.birthDate   | YYYY-MM-DD               |
| PID-8       | Sex   | Patient.gender      | male / female / unknown  |
| PID-11      | Addr  | Patient.address     | line, city, state, zip   |
| PID-13      | Phone | Patient.telecom     | system: phone            |

## Roadmap

- [x] Phase 1 — Parse HL7 ADT message → FHIR Patient
- [ ] Phase 2 — Add OBX parsing → FHIR Observation
- [ ] Phase 3 — Write FHIR resources to PostgreSQL
- [ ] Phase 4 — RabbitMQ producer/consumer pipeline
- [ ] Phase 5 — Data quality checks + dead-letter table
