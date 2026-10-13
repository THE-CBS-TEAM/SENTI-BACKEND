#!/bin/sh
set -e

echo "=== Sentimentri Backend Entrypoint ==="
echo "Running database migrations..."
python manage.py migrate --noinput
echo "Migrations complete."

echo "Collecting static files..."
python manage.py collectstatic --noinput 2>/dev/null || true

echo "Starting: $@"
exec "$@"
