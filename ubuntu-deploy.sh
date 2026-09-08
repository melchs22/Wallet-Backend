#!/usr/bin/env bash
set -euo pipefail

# Run on Ubuntu 22.04/24.04 as a sudo-capable user.
APP_DIR="${APP_DIR:-/var/www/backend}"
APP_USER="${APP_USER:-wallet}"
DB_NAME="${DB_NAME:-walletmvp}"
DB_USER="${DB_USER:-walletapp}"
DB_PASSWORD="${DB_PASSWORD:?Set DB_PASSWORD before running this script}"

sudo apt update
sudo apt install -y python3-venv python3-dev build-essential libpq-dev postgresql postgresql-contrib redis-server nginx git
sudo adduser --system --group --home "$APP_DIR" "$APP_USER" || true
sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER":"$USER" "$APP_DIR"

echo "Create the application files in $APP_DIR, then rerun the service steps in UBUNTU_DEPLOYMENT.md."

sudo -u postgres psql <<SQL
CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';
CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

cat <<ENV
Database URL:
postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}

Generate a Django secret with:
$APP_DIR/.venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
ENV
