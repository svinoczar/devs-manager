#!/bin/bash
set -e

echo "Waiting for PostgreSQL..."
until nc -z db 5432; do
  sleep 0.2
done

echo "Running migrations..."
alembic upgrade head

echo "Starting application..."
exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000
