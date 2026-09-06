#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/wallet-backend}"
cd "$APP_DIR"

if [[ ! -f .env ]]; then
  echo "Missing $APP_DIR/.env; create it from .env.production.example before deploying."
  exit 1
fi

set -a
. ./.env
set +a

.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py check --deploy
sudo systemctl restart wallet-web wallet-celery wallet-celery-beat
sudo systemctl is-active --quiet wallet-web
sudo systemctl is-active --quiet wallet-celery
sudo systemctl is-active --quiet wallet-celery-beat
curl --fail --silent --show-error http://127.0.0.1:8000/ >/dev/null
printf 'Backend deployment completed.\n'
