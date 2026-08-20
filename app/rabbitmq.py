"""
Shared RabbitMQ connection helper used by both producer and consumer.
Reads connection details from environment variables.
"""

import os
import pika
from dotenv import load_dotenv

load_dotenv()

# The queue name both producer and consumer use
QUEUE_NAME = os.getenv("RABBITMQ_QUEUE", "hl7_inbox")


def get_connection() -> pika.BlockingConnection:
    """
    Create and return a blocking RabbitMQ connection.
    Both producer and consumer call this to get a connection.
    """
    credentials = pika.PlainCredentials(
        username=os.getenv("RABBITMQ_USER", "guest"),
        password=os.getenv("RABBITMQ_PASS", "guest"),
    )
    parameters = pika.ConnectionParameters(
        host=os.getenv("RABBITMQ_HOST", "localhost"),
        port=int(os.getenv("RABBITMQ_PORT", 5672)),
        credentials=credentials,
    )
    return pika.BlockingConnection(parameters)
