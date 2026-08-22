# HL7 v2 → FHIR Pipeline

A healthcare data engineering pipeline that ingests HL7 v2 ADT messages, validates them, transforms them into FHIR R4 resources, stores them in PostgreSQL, and models them into analytics tables using dbt — all orchestrated by Apache Airflow.

## Part of a two-project healthcare platform

This pipeline is the **write side** of a healthcare data platform. It pairs with [fhir-patient-api](https://github.com/Srmaraghu/fhir-patient-api) — a FHIR REST API that serves the same data from the same database.

Both projects share the same `fhirdb` PostgreSQL database and table schema — HL7 ingested by the pipeline is immediately queryable through the REST API.

## Architecture

```text
Hospital EHR / .hl7 files
          │
          ▼
    Airflow DAG (daily schedule)
          │
          ├── Task 1: setup_db_tables
          ├── Task 2: ingest_hl7_files  ←  parse → validate → FHIR → PostgreSQL
          ├── Task 3: check_dead_letter ←  quality gate (fails if >30% bad)
          ├── Task 4: dbt_run           ←  build analytics tables
          └── Task 5: report_summary
                │
                ▼
         PostgreSQL (fhirdb)
          ├── public.patients          ← raw FHIR Patient JSONB
          ├── public.observations      ← raw FHIR Observation JSONB
          ├── public.dead_letter       ← failed messages with reason codes
          ├── analytics_staging.stg_patients     ← flattened patient columns
          ├── analytics_staging.stg_observations ← flattened observation columns
          └── analytics_marts.fct_observations   ← joined analytics table
```

### RabbitMQ mode (alternative to Airflow batch)

```text
producer.py → RabbitMQ (hl7_inbox) → consumer.py → parse → validate → FHIR → PostgreSQL
```

## Features

- Parses HL7 v2 ADT messages — PID (demographics) and OBX (lab observations)
- Transforms to FHIR R4 — Patient and Observation resources
- Data quality validation — rejects messages with missing patient ID, invalid DOB, missing LOINC codes
- Dead-letter table — failed messages stored with reason code
- Idempotent inserts — MSH-10 (message control ID) as dedup key
- Atomic transactions — patient + all observations commit together or not at all
- RabbitMQ producer/consumer — decoupled ingestion and processing
- Airflow DAG — scheduled orchestration with dead-letter quality gate
- dbt analytics layer — flattens raw FHIR JSONB into queryable tables with 8 data tests
- 79 pytest tests + GitHub Actions CI

## Project Structure

```text
hl7-fhir-pipeline/
│
├── app/
│   ├── parser.py        ← HL7 v2 parser (PID + OBX segments)
│   ├── transformer.py   ← FHIR R4 Patient + Observation builder
│   ├── validator.py     ← data quality checks + reason codes
│   ├── database.py      ← PostgreSQL (atomic message persistence)
│   ├── rabbitmq.py      ← RabbitMQ connection helper
│   ├── producer.py      ← publishes .hl7 files to queue
│   ├── consumer.py      ← processes messages from queue
│   └── main.py          ← batch mode entry point
│
├── dags/
│   └── hl7_pipeline_dag.py  ← Airflow DAG (5 tasks)
│
├── hl7_analytics/           ← dbt project
│   ├── models/
│   │   ├── staging/
│   │   │   ├── stg_patients.sql
│   │   │   └── stg_observations.sql
│   │   └── marts/
│   │       └── fct_observations.sql
│   └── dbt_project.yml
│
├── data/hl7/inbox/      ← drop .hl7 files here
├── tests/               ← 79 pytest tests
├── Dockerfile           ← custom Airflow image with all deps
├── docker-compose.yml   ← postgres + rabbitmq + airflow
└── requirements.txt
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

**2. Start all services (builds custom Airflow image on first run)**

```bash
docker compose up -d
```

This starts:
- PostgreSQL on port `5432`
- RabbitMQ on port `5672` (management UI at http://localhost:15672 — guest/guest)
- Airflow webserver at http://localhost:8080 (user: airflow / pass: airflow)
- Airflow scheduler

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

### Airflow (recommended)

Go to http://localhost:8080 → find `hl7_fhir_pipeline` → click **▶ Trigger DAG**

Watches all 5 tasks go green. After the run, query analytics:

```bash
docker exec hl7-fhir-pipeline-db-1 psql -U fhiruser -d fhirdb \
  -c "SELECT family_name, loinc_code, value, unit FROM analytics_marts.fct_observations;"
```

### Batch mode (no queue)

```bash
python -m app.main
```

### Queue mode (RabbitMQ)

```bash
# terminal 1
python -m app.consumer

# terminal 2
python -m app.producer
```

## Running Tests

```bash
pytest tests/ -v
```

## HL7 → FHIR Field Mapping

### Patient (PID segment)

| HL7 Field | Description     | FHIR Element             |
|-----------|----------------|--------------------------|
| PID-3     | MR number       | Patient.identifier.value |
| PID-5     | Patient name    | Patient.name             |
| PID-7     | Date of birth   | Patient.birthDate        |
| PID-8     | Gender          | Patient.gender           |
| PID-11    | Address         | Patient.address          |
| PID-13    | Phone           | Patient.telecom          |
| MSH-10    | Message ctrl ID | deduplication key        |

### Observation (OBX segment)

| HL7 Field | Description     | FHIR Element                    |
|-----------|----------------|---------------------------------|
| OBX-3     | LOINC code      | Observation.code.coding         |
| OBX-5     | Result value    | Observation.valueQuantity.value |
| OBX-6     | Units           | Observation.valueQuantity.unit  |
| OBX-7     | Reference range | Observation.referenceRange      |
| OBX-8     | Abnormal flag   | (stored in FHIR resource)       |
| OBX-11    | Status (F/P/C)  | Observation.status              |

## Validation Rules

| Reason Code                 | Condition                                 |
|-----------------------------|-------------------------------------------|
| MISSING_PATIENT_ID          | PID-3 is empty                            |
| MISSING_MESSAGE_CONTROL_ID  | MSH-10 is empty                           |
| MISSING_DOB                 | PID-7 is empty                            |
| INVALID_DOB                 | PID-7 is not a real date or is in future  |
| INVALID_GENDER              | PID-8 is not a recognised HL7 gender code |
| MISSING_LOINC_CODE          | OBX segment has no LOINC code             |

## Tech Stack

| Tool           | Purpose                              |
|----------------|--------------------------------------|
| Python         | Core pipeline language               |
| hl7apy         | HL7 v2 message parsing               |
| psycopg        | PostgreSQL driver (pipeline)         |
| pika           | RabbitMQ client                      |
| PostgreSQL     | FHIR resource storage + analytics    |
| RabbitMQ       | Message broker                       |
| Apache Airflow | Pipeline orchestration + scheduling  |
| dbt            | Analytics modeling (staging + marts) |
| pytest         | Test framework (79 tests)            |
| Docker         | Local infrastructure                 |
| GitHub Actions | CI (runs tests on push and PR)       |
