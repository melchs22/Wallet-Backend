# Ubuntu deployment: Wallet backend

This guide deploys the Django API, PostgreSQL, Redis, Celery worker, Celery Beat, and the Next.js business frontend on Ubuntu at `178.128.156.225` without a domain.

The server-side commands require SSH access. They are prepared here but have not been run remotely because no SSH credentials were provided.

## Fast path: one command

After adding the server's SSH key and logging into Ubuntu, this single command creates `/var/www/backend` and `/var/www/frontend`, clones both GitHub repositories, installs the services, creates PostgreSQL, writes environment files, builds the frontend, configures Nginx, and starts Django/Celery/Beat/Next.js:

```bash
curl -fsSL https://raw.githubusercontent.com/melchs22/Wallet-Backend/main/server-bootstrap.sh | sudo -E bash
```

The command prompts for the PostgreSQL password and Google OAuth credentials. It generates the Django and QR secrets automatically. The script is idempotent for the repository directories and database role, but review the existing server before running it because it will reset cloned repositories to their `main` branch.

For a non-interactive run from a secure shell session:

```bash
export DB_PASSWORD='use-a-strong-password'
export GOOGLE_CLIENT_ID='your-google-client-id'
export GOOGLE_CLIENT_SECRET='your-google-client-secret'
curl -fsSL https://raw.githubusercontent.com/melchs22/Wallet-Backend/main/server-bootstrap.sh | sudo -E bash
```

## 1. Server prerequisites

Use Ubuntu 22.04 or 24.04 with a sudo-capable account. Point the server firewall at these ports:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 3000/tcp
sudo ufw enable
```

Port `8000` should remain private; Nginx proxies `/api/` to Django.

The production repositories are:

- Backend: `https://github.com/melchs22/Wallet-Backend.git`
- Business frontend: `https://github.com/melchs22/dsd-wallet.git`

Clone these exact repositories on the server:

```bash
sudo mkdir -p /var/www/backend /var/www/frontend
sudo chown -R "$USER":"$USER" /var/www/backend /var/www/frontend
git clone https://github.com/melchs22/Wallet-Backend.git /var/www/backend
git clone https://github.com/melchs22/dsd-wallet.git /var/www/frontend
git -C /var/www/backend branch --show-current
git -C /var/www/frontend branch --show-current
```

## 2. PostgreSQL credentials

Choose a strong password locally and keep it in the server environment only. This example uses:

```text
Database: walletmvp
User: walletapp
Password: generate-a-unique-32-character-password
Host: 127.0.0.1
Port: 5432
```

Create the database:

```bash
sudo -u postgres psql
CREATE USER walletapp WITH PASSWORD 'REPLACE_WITH_A_GENERATED_PASSWORD';
CREATE DATABASE walletmvp OWNER walletapp;
GRANT ALL PRIVILEGES ON DATABASE walletmvp TO walletapp;
\q
```

Generate a password with `openssl rand -base64 32`. Do not commit it, paste it into chat, or place it in a tracked file.

## 3. Python environment

```bash
cd /var/www/backend
sudo apt update
sudo apt install -y python3-venv python3-dev build-essential libpq-dev postgresql postgresql-contrib redis-server nginx
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Create `/var/www/backend/.env` with mode `600`:

```dotenv
DJANGO_SETTINGS_MODULE=walletmvp.settings
SECRET_KEY=GENERATE_WITH_DJANGO
DEBUG=False
ALLOWED_HOSTS=178.128.156.225,localhost,127.0.0.1
DATABASE_URL=postgresql://walletapp:REPLACE_PASSWORD@127.0.0.1:5432/walletmvp
DB_CONN_MAX_AGE=60
FRONTEND_ORIGIN=http://178.128.156.225:3000
FRONTEND_ORIGIN_URL=http://178.128.156.225:3000
CORS_ALLOWED_ORIGINS=http://178.128.156.225:3000
CSRF_TRUSTED_ORIGINS=http://178.128.156.225,http://178.128.156.225:3000
SESSION_COOKIE_SECURE=False
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SECURE=False
CSRF_COOKIE_SAMESITE=Lax
GOOGLE_CLIENT_ID=YOUR_GOOGLE_CLIENT_ID
GOOGLE_CLIENT_SECRET=YOUR_GOOGLE_CLIENT_SECRET
QR_SIGNING_SECRET=GENERATE_ANOTHER_RANDOM_SECRET
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
```

```bash
chmod 600 /var/www/backend/.env
```

For Google OAuth, add `http://178.128.156.225:3000/auth/callback` as an authorized redirect URI. Google may require a verified domain for production OAuth; use a domain and HTTPS before public launch.

## 4. SQLite to PostgreSQL migration

On the existing machine, export application data before changing `DATABASE_URL`:

```bash
cd /path/to/Wallet-Backend
./export_sqlite_data.sh backups/pre-postgres
```

Copy `backups/pre-postgres/wallet-data.json` to the server. Then on Ubuntu:

```bash
cd /var/www/backend
. .venv/bin/activate
set -a; . ./.env; set +a
python manage.py migrate
python manage.py loaddata /var/www/backend/backups/pre-postgres/wallet-data.json
python manage.py collectstatic --noinput
python manage.py check --deploy
```

The JSON fixture is the portable database dump for Django rows. Keep the original SQLite copy until the PostgreSQL data has been verified. After import, create a PostgreSQL-native backup:

```bash
mkdir -p /opt/backups
pg_dump --format=custom --file=/opt/backups/walletmvp-$(date +%Y%m%d-%H%M).dump walletmvp
```

Verify counts and login before deleting any SQLite backup.

## 5. Systemd services

Create `/etc/systemd/system/wallet-web.service`:

```ini
[Unit]
Description=Wallet Django API
After=network.target postgresql.service redis-server.service

[Service]
User=wallet
Group=wallet
WorkingDirectory=/var/www/backend
EnvironmentFile=/var/www/backend/.env
ExecStart=/var/www/backend/.venv/bin/gunicorn walletmvp.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/wallet-celery.service`:

```ini
[Unit]
Description=Wallet Celery worker
After=network.target redis-server.service postgresql.service

[Service]
User=wallet
Group=wallet
WorkingDirectory=/var/www/backend
EnvironmentFile=/var/www/backend/.env
ExecStart=/var/www/backend/.venv/bin/celery -A walletmvp worker -l info --concurrency 2
Restart=always

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/wallet-celery-beat.service`:

```ini
[Unit]
Description=Wallet Celery Beat
After=network.target redis-server.service postgresql.service

[Service]
User=wallet
Group=wallet
WorkingDirectory=/var/www/backend
EnvironmentFile=/var/www/backend/.env
ExecStart=/var/www/backend/.venv/bin/celery -A walletmvp beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable them:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now redis-server wallet-web wallet-celery wallet-celery-beat
sudo systemctl status wallet-web wallet-celery wallet-celery-beat --no-pager
journalctl -u wallet-web -u wallet-celery -u wallet-celery-beat -f
```

## 6. Nginx API proxy

Create `/etc/nginx/sites-available/wallet`:

```nginx
server {
    listen 80;
    server_name 178.128.156.225;

    location /static/ {
        alias /var/www/backend/staticfiles/;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/wallet /etc/nginx/sites-enabled/wallet
sudo nginx -t
sudo systemctl reload nginx
```

The public URLs become:

- Business frontend: `http://178.128.156.225/business`
- API: `http://178.128.156.225/api/`
- Swagger: `http://178.128.156.225/api/docs/`

## 7. Business frontend

Create `/var/www/frontend/.env.production`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://178.128.156.225/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=YOUR_GOOGLE_CLIENT_ID
```

Install and run it:

```bash
cd /var/www/frontend
npm ci
npm run build
npm run start -- --hostname 127.0.0.1 --port 3000
```

Create `/etc/systemd/system/wallet-frontend.service`:

```ini
[Unit]
Description=Wallet business frontend
After=network.target

[Service]
User=wallet
Group=wallet
WorkingDirectory=/var/www/frontend
EnvironmentFile=/var/www/frontend/.env.production
ExecStart=/usr/bin/npm run start -- --hostname 127.0.0.1 --port 3000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wallet-frontend
```

## 8. GitHub deployment

The backend repository `https://github.com/melchs22/Wallet-Backend` includes `.github/workflows/deploy.yml`; the business frontend repository `https://github.com/melchs22/dsd-wallet` has its own workflow at `.github/workflows/deploy.yml`. Both workflows validate before deploying over SSH.

The workflows assume both repositories use the `main` branch. If the repositories use another default branch, change the `branches: [main]` line in the corresponding workflow before pushing.

Add these Actions secrets to each GitHub repository:

```text
DEPLOY_HOST=178.128.156.225
DEPLOY_USER=your-ubuntu-user
DEPLOY_SSH_PRIVATE_KEY=the-private-key-for-that-user
APP_DIR=/var/www/backend       # backend repository only
FRONTEND_DIR=/var/www/frontend      # frontend repository only
GOOGLE_CLIENT_ID=...              # frontend repository only
```

The server must already contain `.env` at `/var/www/backend/.env` and `.env.production` at `/var/www/frontend/.env.production`. These files are intentionally excluded from rsync and never stored in GitHub.

On the Ubuntu user, allow only the required service restarts without an interactive password prompt by adding a narrow sudoers rule with `sudo visudo`:

```text
your-ubuntu-user ALL=(root) NOPASSWD: /bin/systemctl restart wallet-web wallet-celery wallet-celery-beat, /bin/systemctl restart wallet-frontend, /bin/systemctl is-active wallet-web, /bin/systemctl is-active wallet-celery, /bin/systemctl is-active wallet-celery-beat
```

Push to `main` or manually run the `Deploy wallet platform` and `Deploy business frontend` workflows. Review the workflow logs and then check `http://178.128.156.225/`.

The backend workflow deploys only `/var/www/backend`; the frontend workflow deploys only `/var/www/frontend`. They are intentionally independent because these are separate GitHub repositories.

## 9. Security before public launch

IP-only HTTP is suitable for initial testing, not production money movement. Before live credentials or real mobile-money rails:

1. Point a domain at `178.128.156.225`.
2. Add HTTPS with Certbot and set `SESSION_COOKIE_SECURE=True` and `CSRF_COOKIE_SECURE=True`.
3. Rotate `SECRET_KEY`, `QR_SIGNING_SECRET`, PostgreSQL password, and Google credentials.
4. Restrict PostgreSQL and Redis to localhost.
5. Set `ALLOWED_HOSTS`, CORS, and CSRF trusted origins to the final HTTPS domains.
6. Keep `.env`, SQLite copies, JSON fixtures, and PostgreSQL dumps outside git.
7. Configure real object storage before accepting KYC document uploads.
