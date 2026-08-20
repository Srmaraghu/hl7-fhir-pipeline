# HL7 v2 → FHIR Pipeline

A healthcare data engineering pipeline that ingests HL7 v2 ADT messages, validates them, transforms them into FHIR R4 resources, and stores them in PostgreSQL. Supports both batch processing and a RabbitMQ-based producer/consumer architecture.

## Part of a two-project healthcare platform

This pipeline is the **write side** of a healthcare data platform. It pairs with [fhir-patient-api](https://github.com/Srmaraghu/fhir-patient-api) which is the **read side** — a FHIR REST API that serves the same data.

```
HL7 v2 message (.hl7 file)
          ↓
  hl7-fhir-pipeline        ← YOU ARE HERE
  (parse, validate,
   transform, write)
          ↓
     PostgreSQL
     (fhirdb)
      patients
    observations
          ↓
  fhir-patient-api         ← github.com/Srmaraghu/fhir-patient-api
  (FHIR REST API,
   read/serve)
          ↓
GET /Patient/{id}
GET /Observation?patient={id}
```

Both projects share the same `fhirdb` PostgreSQL database and the same table schema — so HL7 ingested by the pipeline is immediately queryable through the REST API. They use different connection libraries (psycopg vs asyncpg) but write to the same tables in the same format.

## Architecture

```
Hospital EHR / .hl7 files
          │
          ▼
    producer.py
  (publishes to queue)
          │
          ▼
    RabbitMQ Queue
    (hl7_inbox)
          │
          ▼
    consumer.py
  (always running)
          │
    ┌─────┴──────┐
    │            │
    ▼            ▼
parser.py    validator.py
(PID + OBX)  (data quality)
    │            │
    │         invalid → dead_letter table
    │
    ▼
transformer.py
(FHIR R4 resources)
    │
    ▼
database.py
(PostgreSQL)
    │
    ├── patients table
    └── observations table
```

## Features

- Parses HL7 v2 ADT messages — extracts PID (patient demographics) and OBX (lab observations) segments
- Transforms to FHIR R4 — Patient and Observation resources
- Data quality validation — rejects messages with missing patient ID, invalid DOB, missing LOINC codes
- Dead-letter table — failed messages stored with reason code for investigation
- Idempotent inserts — uses MSH-10 (message control ID) as dedup key, safe to re-run
- RabbitMQ pipeline — producer publishes .hl7 files to queue, consumer processes continuously
- Batch mode — direct file processing without a queue
- 79 pytest tests covering parser, transformer, and validator
- GitHub Actions CI — runs tests on every push and PR

## Project Structure

```
hl7-fhir-pipeline/
│
├── app/
│   ├── parser.py        ← HL7 v2 parser (PID + OBX segments)
│   ├── transformer.py   ← FHIR R4 Patient + Observation builder
│   ├── validator.py     ← data quality checks + reason codes
│   ├── database.py      ← PostgreSQL connection + table management
│   ├── rabbitmq.py      ← RabbitMQ connection helper
│   ├── producer.py      ← publishes .hl7 files to queue
│   ├── consumer.py      ← processes messages from queue
│   └── main.py          ← batch mode entry point
│
├── data/
│   └── hl7/
│       └── inbox/       ← drop .hl7 files here for processing
│           ├── patient_001.hl7
│           ├── patient_002.hl7
│           └── bad_*.hl7   ← intentionally invalid test files
│
├── tests/
│   ├── test_parser.py
│   ├── test_transformer.py
│   └── test_validator.py
│
├── .github/workflows/ci.yml
├── docker-compose.yml
├── requirements.txt
└── .env
```

## Setup

**1. Clone and create virtual environment**

```bash
git clone https://github.com/Srmaraghu/hl7-fhir-pipeline.git
cd hl7-fhir-pipeline
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**2. Start PostgreSQL and RabbitMQ**

```bash
docker compose up -d
```

This starts:
- PostgreSQL on port `5432`
- RabbitMQ on port `5672` (management UI at http://localhost:15672 — guest/guest)

**3. Create a `.env` file**

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=fhirdb
DB_USER=fhiruser
DB_PASSWORD=fhirpassword

RABBITMQ_HOST=localhost
RABBITMQ_PORT=5672
RABBITMQ_USER=guest
RABBITMQ_PASS=guest
RABBITMQ_QUEUE=hl7_inbox
```

## Running the Pipeline

### Batch mode (no queue)

```bash
python -m app.main
```

Processes all `.hl7` files in `data/hl7/inbox/` and prints a summary:

```
Total processed : 5
Valid           : 2
Invalid / Failed: 3
  bad_missing_patient_id.hl7  [MISSING_PATIENT_ID]
  bad_invalid_dob.hl7         [INVALID_DOB]
  bad_missing_obx_loinc.hl7   [MISSING_LOINC_CODE]
```

### Queue mode (RabbitMQ)

In one terminal, start the consumer:

```bash
python -m app.consumer
```

In another terminal, run the producer:

```bash
python -m app.producer
```

The producer reads all `.hl7` files from `inbox/` and publishes them to the queue. The consumer processes each message as it arrives.

## Running Tests

```bash
pytest tests/ -v
```

79 tests across parser, transformer, and validator modules.

## HL7 → FHIR Field Mapping

### Patient (PID segment)

| HL7 Field | Description      | FHIR Element             |
|-----------|-----------------|--------------------------|
| PID-3     | MR number        | Patient.identifier.value |
| PID-5     | Patient name     | Patient.name             |
| PID-7     | Date of birth    | Patient.birthDate        |
| PID-8     | Gender           | Patient.gender           |
| PID-11    | Address          | Patient.address          |
| PID-13    | Phone            | Patient.telecom          |
| MSH-10    | Message ctrl ID  | deduplication key        |

### Observation (OBX segment)

| HL7 Field | Description      | FHIR Element                      |
|-----------|-----------------|-----------------------------------|
| OBX-3     | LOINC code       | Observation.code.coding           |
| OBX-5     | Result value     | Observation.valueQuantity.value   |
| OBX-6     | Units            | Observation.valueQuantity.unit    |
| OBX-7     | Reference range  | Observation.referenceRange        |
| OBX-11    | Status (F/P/C)   | Observation.status                |

## Validation Rules

| Reason Code                  | Condition                                  |
|-----------------------------|--------------------------------------------|
| MISSING_PATIENT_ID          | PID-3 is empty                             |
| MISSING_MESSAGE_CONTROL_ID  | MSH-10 is empty                            |
| MISSING_DOB                 | PID-7 is empty                             |
| INVALID_DOB                 | PID-7 is not a real date or is in future   |
| INVALID_GENDER              | PID-8 is not a recognised HL7 gender code  |
| MISSING_LOINC_CODE          | OBX segment has no LOINC code              |

## Tech Stack

| Tool        | Purpose                        |
|-------------|-------------------------------|
| Python      | Core pipeline language         |
| hl7apy      | HL7 v2 message parsing         |
| psycopg     | PostgreSQL driver              |
| pika        | RabbitMQ client                |
| PostgreSQL  | FHIR resource storage          |
| RabbitMQ    | Message broker                 |
| pytest      | Test framework                 |
| Docker      | Local infrastructure           |
| GitHub Actions | CI/CD                       |
