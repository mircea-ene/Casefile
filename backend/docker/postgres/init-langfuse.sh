#!/bin/sh
# Langfuse keeps its own database and role in this Postgres (runs only on an empty data directory).
set -e
psql -v ON_ERROR_STOP=1 -v pw="$LANGFUSE_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
CREATE ROLE langfuse LOGIN PASSWORD :'pw';
CREATE DATABASE langfuse OWNER langfuse;
SQL
