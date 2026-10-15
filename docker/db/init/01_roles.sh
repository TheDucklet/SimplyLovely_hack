#!/bin/bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" \
    -v loader_password="$GEOSTART_DB_LOADER_PASSWORD" \
    -v api_password="$GEOSTART_DB_API_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE ROLE geostart_loader LOGIN PASSWORD :'loader_password';
CREATE ROLE geostart_api LOGIN PASSWORD :'api_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA geo AUTHORIZATION geostart_loader;
GRANT USAGE ON SCHEMA geo TO geostart_api;
ALTER DEFAULT PRIVILEGES FOR ROLE geostart_loader IN SCHEMA geo GRANT SELECT ON TABLES TO geostart_api;
SQL
