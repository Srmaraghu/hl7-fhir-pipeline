"""
Reads all .hl7 files from data/hl7/inbox/ and publishes each one
as a raw message to a RabbitMQ queue.

This simulates what a hospital EHR system does in real life —
it sends HL7 messages to a message broker whenever a patient event occurs
(admission, discharge, lab result, etc.)

In real healthcare systems the producer would be:
  - An EHR system (Epic, Cerner) sending over MLLP
  - A file watcher picking up dropped .hl7 files
  - An HL7 interface engine like Mirth Connect

Run:
  python -m app.producer
"""

import glob
import os

import pika

from app.rabbitmq import get_connection, QUEUE_NAME

INBOX = os.path.join(os.path.dirname(__file__), "..", "data", "hl7", "inbox")


def run():
    print("=" * 60)
    print("HL7 Producer")
    print("=" * 60)

    hl7_files = sorted(glob.glob(os.path.join(INBOX, "*.hl7")))

    if not hl7_files:
        print(f"\nNo .hl7 files found in {INBOX}")
        return

    print(f"\nFound {len(hl7_files)} file(s) — publishing to queue '{QUEUE_NAME}'\n")

    # connect to RabbitMQ
    connection = get_connection()
    channel = connection.channel()

    # declare the queue (creates it if it doesn't exist yet)
    # durable=True means the queue survives a RabbitMQ restart
    channel.queue_declare(queue=QUEUE_NAME, durable=True)

    published = 0
    for filepath in hl7_files:
        filename = os.path.basename(filepath)

        with open(filepath, "r") as f:
            raw_hl7 = f.read()

        # publish the raw HL7 text as the message body
        # delivery_mode=2 makes the message persistent (survives broker restart)
        channel.basic_publish(
            exchange="",
            routing_key=QUEUE_NAME,
            body=raw_hl7.encode("utf-8"),
            properties=pika.BasicProperties(
                delivery_mode=2,
                content_type="text/plain",
                headers={"filename": filename},
            ),
        )

        print(f" Published: {filename}")
        published += 1

    connection.close()

    print(f"Done. Published {published} message(s) to '{QUEUE_NAME}'.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    run()
