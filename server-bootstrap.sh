#!/usr/bin/env bash
set -Eeuo pipefail

# One-command Ubuntu bootstrap for the two production GitHub repositories.
# Run as a sudo-capable Ubuntu user:
#   curl -fsSL https://raw.githubusercontent.com/melchs22/Wallet-Backend/main/server-bootstrap.sh | sudo -E bash

BACKEND_DIR="${BACKEND_DIR:-/var/www/backend}"
FRONTEND_DIR="${FRONTEND_DIR:-/var/www/frontend}"
APP_USER="${APP_USER:-wallet}"
DB_NAME="${DB_NAME:-walletmvp}"
DB_USER="${DB_USER:-walletapp}"
DB_PASSWORD="${DB_PASSWORD:-}"
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-}"
GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-}"

if [[ -z "$DB_PASSWORD" ]]; then
  read -r -s -p 'PostgreSQL password: ' DB_PASSWORD
  printf '\n'
fi
if [[ -z "$GOOGLE_CLIENT_ID" ]]; then read -r -p 'Google client ID: ' GOOGLE_CLIENT_ID; fi
if [[ -z "$GOOGLE_CLIENT_SECRET" ]]; then read -r -s -p 'Google client secret: ' GOOGLE_CLIENT_SECRET; printf '\n'; fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git curl nginx redis-server postgresql postgresql-contrib python3-venv python3-dev build-essential libpq-dev ca-certificates
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

id -u "$APP_USER" >/dev/null 2>&1 || adduser --system --group --home "$BACKEND_DIR" "$APP_USER"
mkdir -p /var/www "$BACKEND_DIR" "$FRONTEND_DIR"
chown -R "$APP_USER":"$APP_USER" /var/www

if [[ ! -d "$BACKEND_DIR/.git" ]]; then
  git clone https://github.com/melchs22/Wallet-Backend.git "$BACKEND_DIR"
else
  git -C "$BACKEND_DIR" fetch origin main
  git -C "$BACKEND_DIR" reset --hard origin/main
fi
if [[ ! -d "$FRONTEND_DIR/.git" ]]; then
  git clone https://github.com/melchs22/dsd-wallet.git "$FRONTEND_DIR"
else
  git -C "$FRONTEND_DIR" fetch origin main
  git -C "$FRONTEND_DIR" reset --hard origin/main
fi

sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
  ELSE
    ALTER ROLE ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';
  END IF;
END
\$\$;
SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec
GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};
SQL

python3 -m venv "$BACKEND_DIR/.venv"
"$BACKEND_DIR/.venv/bin/pip" install --upgrade pip
"$BACKEND_DIR/.venv/bin/pip" install -r "$BACKEND_DIR/requirements.txt"

SECRET_KEY="$($BACKEND_DIR/.venv/bin/python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
QR_SECRET="$(openssl rand -hex 32)"
cat > "$BACKEND_DIR/.env" <<ENV
DJANGO_SETTINGS_MODULE=walletmvp.settings
SECRET_KEY=$SECRET_KEY
DEBUG=False
ALLOWED_HOSTS=178.128.156.225,localhost,127.0.0.1
DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:5432/${DB_NAME}
DB_CONN_MAX_AGE=60
FRONTEND_ORIGIN=http://178.128.156.225
FRONTEND_ORIGIN_URL=http://178.128.156.225
CORS_ALLOWED_ORIGINS=http://178.128.156.225
CSRF_TRUSTED_ORIGINS=http://178.128.156.225
SESSION_COOKIE_SECURE=False
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SECURE=False
CSRF_COOKIE_SAMESITE=Lax
GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=$GOOGLE_CLIENT_SECRET
QR_SIGNING_SECRET=$QR_SECRET
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
ENV
chmod 600 "$BACKEND_DIR/.env"

cat > "$FRONTEND_DIR/.env.production" <<ENV
NEXT_PUBLIC_API_BASE_URL=http://178.128.156.225/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=$GOOGLE_CLIENT_ID
ENV
chmod 600 "$FRONTEND_DIR/.env.production"

cd "$BACKEND_DIR"
set -a; . ./.env; set +a
"$BACKEND_DIR/.venv/bin/python" manage.py migrate --noinput
"$BACKEND_DIR/.venv/bin/python" manage.py collectstatic --noinput

cd "$FRONTEND_DIR"
npm ci
npm run build

cat > /etc/systemd/system/wallet-web.service <<UNIT
[Unit]
Description=Wallet Django API
After=network.target postgresql.service redis-server.service
[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$BACKEND_DIR/.env
ExecStart=$BACKEND_DIR/.venv/bin/gunicorn walletmvp.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/wallet-celery.service <<UNIT
[Unit]
Description=Wallet Celery worker
After=network.target redis-server.service postgresql.service
[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$BACKEND_DIR/.env
ExecStart=$BACKEND_DIR/.venv/bin/celery -A walletmvp worker -l info --concurrency 2
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/wallet-celery-beat.service <<UNIT
[Unit]
Description=Wallet Celery Beat
After=network.target redis-server.service postgresql.service
[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$BACKEND_DIR/.env
ExecStart=$BACKEND_DIR/.venv/bin/celery -A walletmvp beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/wallet-frontend.service <<UNIT
[Unit]
Description=Wallet business frontend
After=network.target
[Service]
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$FRONTEND_DIR
EnvironmentFile=$FRONTEND_DIR/.env.production
ExecStart=/usr/bin/npm run start -- --hostname 127.0.0.1 --port 3000
Restart=always
[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/nginx/sites-available/wallet <<NGINX
server {
    listen 80;
    server_name 178.128.156.225;
    location /static/ { alias $BACKEND_DIR/staticfiles/; }
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX
ln -sf /etc/nginx/sites-available/wallet /etc/nginx/sites-enabled/wallet
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl daemon-reload
systemctl enable --now redis-server wallet-web wallet-celery wallet-celery-beat wallet-frontend
systemctl reload nginx || systemctl restart nginx
curl --fail --silent --show-error http://127.0.0.1/ >/dev/null
printf '\nDeployment complete: http://178.128.156.225/business\n'
