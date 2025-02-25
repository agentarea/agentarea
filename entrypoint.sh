#!/bin/sh

# Wait for the database if DB_HOST and DB_PORT are set
if [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
  echo "Waiting for database at ${DB_HOST}:${DB_PORT}..."
  while ! nc -z "$DB_HOST" "$DB_PORT"; do
    sleep 1
  done
fi

# Optionally run alembic migrations if RUN_MIGRATIONS is set to true
if [ "$RUN_MIGRATIONS" = "true" ]; then
  echo "Running alembic migrations..."
  python -m app.cli --migrate
fi

# Execute the given command
exec "$@" 