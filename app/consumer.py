"""
Listens to the RabbitMQ queue and processes each HL7 message
through the full pipeline:

  RabbitMQ queue
       ↓
  parse raw HL7 text   (parser.py)
       ↓
  validate PID + OBX   (validator.py)
       ↓
  transform to FHIR    (transformer.py)
       ↓
  save to PostgreSQL   (database.py)

The consumer runs continuously — it blocks and waits for new messages.
This is the "always on" part of the pipeline.
"""

import os
import tempfile

import pika

from app.rabbitmq import get_connection, QUEUE_NAME
from app.parser import parse_hl7_file
from app.validator import validate, extract_reason_code
from app.transformer import pid_to_fhir_patient, obx_list_to_fhir_observations
from app.database import (
    create_tables,
    persist_message,
    insert_dead_letter,
)

# counters — tracked across all messages processed in this session
_stats = {"total": 0, "valid": 0, "invalid": 0}


def process_message(channel, method, properties, body: bytes):
    """
    Callback fired by pika every time a message arrives from the queue.

    Parameters (set by pika):
        channel  — the RabbitMQ channel
        method   — delivery metadata (used for ack/nack)
        properties — message headers (we use 'filename' header)
        body     — raw bytes of the HL7 message
    """
    _stats["total"] += 1

    # get the original filename from the message header (for dead-letter logging)
    filename = "unknown.hl7"
    if properties.headers and "filename" in properties.headers:
        filename = properties.headers["filename"]

    print(f"\n{'─' * 40}")
    print(f"[Consumer] Received: {filename}")

    try:
        raw_hl7 = body.decode("utf-8")

        # hl7apy needs a file path — write to a temp file, parse, delete
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".hl7", delete=False
        ) as tmp:
            tmp.write(raw_hl7)
            tmp_path = tmp.name

        try:
            pid_data, obx_data = parse_hl7_file(tmp_path)
        finally:
            os.unlink(tmp_path)  # always clean up the temp file

        # validate
        is_valid, full_reason = validate(pid_data, obx_data)

        if not is_valid:
            reason_code = extract_reason_code(full_reason)
            insert_dead_letter(filename, reason_code, raw_hl7)
            print(f"  INVALID - {full_reason}")
            _stats["invalid"] += 1

        else:
            # transform
            fhir_patient = pid_to_fhir_patient(pid_data)
            fhir_observations = obx_list_to_fhir_observations(obx_data)

            # save — single transaction for the whole message
            mr_number          = pid_data.get("patient_id", "")
            message_control_id = pid_data.get("message_control_id", "")

            obs_payloads = [
                {
                    "fhir_obs":     fhir_obs,
                    "loinc_code":   obs.get("loinc_code", ""),
                    "obx_sequence": obs.get("obx_sequence", str(i + 1)),
                    "description":  obs.get("description", ""),
                }
                for i, (obs, fhir_obs) in enumerate(zip(obx_data, fhir_observations))
            ]

            patient_fhir_id = persist_message(
                mr_number=mr_number,
                fhir_patient=fhir_patient,
                message_control_id=message_control_id,
                observations=obs_payloads,
            )

            print(f"  VALID - patient saved (id={patient_fhir_id}), {len(fhir_observations)} observation(s) saved")
            _stats["valid"] += 1

    except Exception as e:
        print(f"  ERROR - {e}")
        insert_dead_letter(filename, "PARSE_ERROR", body.decode("utf-8", errors="replace"))
        _stats["invalid"] += 1

    finally:
        # always ack the message so RabbitMQ removes it from the queue
        # even if processing failed — we've handled it (dead-lettered it)
        channel.basic_ack(delivery_tag=method.delivery_tag)

    print(f"  [Stats] total={_stats['total']} valid={_stats['valid']} invalid={_stats['invalid']}")


def run():
    print("=" * 60)
    print("HL7 Consumer — waiting for messages")
    print(f"Queue: {QUEUE_NAME}")
    print("=" * 60)

    # ensure DB tables exist before processing starts
    create_tables()

    connection = get_connection()
    channel = connection.channel()

    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    # only fetch one message at a time — don't overwhelm the consumer
    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(
        queue=QUEUE_NAME,
        on_message_callback=process_message,
    )

    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        print(f"\n\n{'=' * 60}")
        print("Consumer stopped.")
        print(f"  Total processed : {_stats['total']}")
        print(f"  Valid           : {_stats['valid']}")
        print(f"  Invalid         : {_stats['invalid']}")
        print(f"{'=' * 60}")
        channel.stop_consuming()

    connection.close()


if __name__ == "__main__":
    run()
