# hl7_analytics

dbt analytics layer for the HL7 → FHIR pipeline. Flattens raw FHIR JSONB stored
by [hl7-fhir-pipeline](https://github.com/Srmaraghu/hl7-fhir-pipeline) into
clean, queryable analytics tables.

## Profile

Uses the `hl7_analytics` profile. Create `~/.dbt/profiles.yml`:

```yaml
hl7_analytics:
  target: dev
  outputs:
    dev:
      type: postgres
      host: localhost
      port: 5432
      dbname: fhirdb
      user: fhiruser
      password: fhirpassword
      schema: analytics
      threads: 4
```

## Source Tables

| Table | Schema | Description |
|-------|--------|-------------|
| `patients` | public | FHIR R4 Patient resources as JSONB — written by the pipeline |
| `observations` | public | FHIR R4 Observation resources as JSONB — written by the pipeline |

## Models

### Staging (views)

| Model | Description |
|-------|-------------|
| `stg_patients` | Flattens `patients.resource` JSONB → mrn, family_name, gender, birth_date, address, phone |
| `stg_observations` | Flattens `observations.resource` JSONB → loinc_code, description, value, unit, status, reference_range |

### Marts (tables)

| Model | Description |
|-------|-------------|
| `fct_observations` | Joins `stg_observations` and `stg_patients` — one row per observation with full patient context |

## Setup

```bash
cd hl7_analytics
pip install dbt-postgres
dbt debug    # verify connection
```

## Run

```bash
dbt run      # builds all models
dbt test     # runs 8 data quality tests
```

## Tests

- `unique` + `not_null` on all ID columns
- `relationships` check: every `fct_observations.patient_id` must exist in `stg_patients`
