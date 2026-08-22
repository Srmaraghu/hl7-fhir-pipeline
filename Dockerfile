FROM apache/airflow:2.11.1

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc build-essential \
    && rm -rf /var/lib/apt/lists/*

USER airflow

COPY requirements-airflow.txt /requirements-airflow.txt

RUN pip install --no-cache-dir --prefer-binary \
    -r /requirements-airflow.txt
