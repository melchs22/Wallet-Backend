# Wallet Backend Deployment Operations

## Server and application paths

- Server: `ec2-user@51.21.180.12`
- Application root: `/opt/wallet-backend`
- Python virtual environment: `/opt/wallet-backend/.venv`
- Environment file: `/opt/wallet-backend/.env` (permissions `600`; contains secrets)
- Firebase service account: `/opt/wallet-backend/secrets/firebase-service-account.json` (permissions `600`)
- Django settings: `/opt/wallet-backend/walletmvp/settings.py`
- Django project entry point: `/opt/wallet-backend/manage.py`
- Static files: `/opt/wallet-backend/staticfiles`
- Uploaded media: `/opt/wallet-backend/media`
- Git checkout: `/opt/wallet-backend/.git`
- Nginx site configuration: `/etc/nginx/conf.d/wallet.conf`
- TLS certificates: `/etc/letsencrypt/live/apis.dsdwallet.com/`
- Systemd units: `/etc/systemd/system/wallet-web.service`, `/etc/systemd/system/wallet-celery.service`, `/etc/systemd/system/wallet-celery-beat.service`

## SSH connection

```bash
ssh -i /Users/tutumelchizedek/Documents/aws/Tutu.pem ec2-user@51.21.180.12
```

## Service commands

Restart the complete application stack:

```bash
sudo systemctl restart wallet-web wallet-celery wallet-celery-beat
```

Restart only the web API:

```bash
sudo systemctl restart wallet-web
```

Restart only Celery:

```bash
sudo systemctl restart wallet-celery wallet-celery-beat
```

Check application services:

```bash
systemctl is-active wallet-web wallet-celery wallet-celery-beat
sudo systemctl status wallet-web wallet-celery wallet-celery-beat --no-pager
```

Enable services at boot:

```bash
sudo systemctl enable wallet-web wallet-celery wallet-celery-beat
```

## Supporting services

```bash
sudo systemctl status postgresql redis6 nginx --no-pager
sudo systemctl restart postgresql redis6 nginx
```

Redis health check:

```bash
redis-cli ping
```

PostgreSQL health check:

```bash
sudo -u postgres pg_isready
```

## Logs

```bash
sudo journalctl -u wallet-web -f
sudo journalctl -u wallet-celery -f
sudo journalctl -u wallet-celery-beat -f
sudo journalctl -u nginx -f
sudo journalctl -u postgresql -f
sudo journalctl -u redis6 -f
```

View recent logs instead of following:

```bash
sudo journalctl -u wallet-web -u wallet-celery -u wallet-celery-beat --no-pager -n 100
```

## Django management commands

```bash
cd /opt/wallet-backend
source .venv/bin/activate
set -a; source .env; set +a
python manage.py check --deploy
python manage.py migrate --noinput
python manage.py collectstatic --noinput
```

After changing environment variables or application code:

```bash
sudo systemctl restart wallet-web wallet-celery wallet-celery-beat
```

## Updating from GitHub

```bash
cd /opt/wallet-backend
git fetch --depth 1 origin main
git reset --hard origin/main
source .venv/bin/activate
pip install -r requirements.txt
set -a; source .env; set +a
python manage.py migrate --noinput
python manage.py collectstatic --noinput
sudo systemctl restart wallet-web wallet-celery wallet-celery-beat
```

Do not overwrite `.env` or the `secrets/` directory during updates.

## Nginx and HTTPS

Test Nginx configuration:

```bash
sudo nginx -t
```

Reload Nginx after configuration changes:

```bash
sudo systemctl reload nginx
```

API URL:

```text
https://apis.dsdwallet.com
```

Test the API and HTTP redirect:

```bash
curl -I https://apis.dsdwallet.com/api/schema/
curl -I http://apis.dsdwallet.com/api/schema/
```

Certificate status:

```bash
sudo certbot certificates
```

Test automatic renewal:

```bash
sudo certbot renew --dry-run
```

If Nginx configuration was changed manually, run `sudo nginx -t` before reloading it.

## Basic deployment verification

```bash
systemctl is-active postgresql redis6 nginx wallet-web wallet-celery wallet-celery-beat
curl -fsS https://apis.dsdwallet.com/api/schema/ >/dev/null && echo API_OK
redis-cli ping
sudo -u postgres pg_isready
```

## Important security notes

- Never print or commit `/opt/wallet-backend/.env` or the Firebase JSON file.
- Keep AWS inbound TCP ports 80 and 443 open for HTTPS service and certificate renewal; restrict SSH port 22 to trusted IPs when possible.
- Rotate any credential that has been exposed in chat, shell history, logs, or source control.

## Frontend deployment

- Frontend root: `/opt/dsd-wallet`
- Frontend environment: `/opt/dsd-wallet/.env.production`
- Frontend build output: `/opt/dsd-wallet/.next`
- Frontend systemd unit: `/etc/systemd/system/dsd-wallet.service`
- Frontend local listener: `127.0.0.1:3000`
- Frontend Nginx configuration: `/etc/nginx/conf.d/dsd-wallet.conf`
- Frontend URL: `https://dsdwallet.com`
- Frontend API base URL: `https://apis.dsdwallet.com/api`

Restart the frontend:

```bash
sudo systemctl restart dsd-wallet
```

Check frontend status and logs:

```bash
systemctl is-active dsd-wallet
sudo systemctl status dsd-wallet --no-pager
sudo journalctl -u dsd-wallet -f
```

Rebuild the frontend after source or environment changes:

```bash
cd /opt/dsd-wallet
npm ci
npm run build
sudo systemctl restart dsd-wallet
```

The production environment values are in `/opt/dsd-wallet/.env.production`. Values beginning with `NEXT_PUBLIC_` are embedded into the browser bundle during `npm run build`, so rebuild after changing them.

The frontend is built from the local checkout because the GitHub repository is private. To update it from a local checkout, transfer the source to `/opt/dsd-wallet`, then run `npm ci`, `npm run build`, and restart `dsd-wallet`.

## Frontend and backend verification

```bash
systemctl is-active nginx dsd-wallet wallet-web wallet-celery wallet-celery-beat
curl -fsS https://dsdwallet.com/ >/dev/null && echo FRONTEND_OK
curl -fsS https://apis.dsdwallet.com/api/schema/ >/dev/null && echo API_OK
```

## Swapfile for frontend builds

The server uses a 2 GB swapfile to support the Next.js production build on the small EC2 instance:

```text
/swapfile
```

Check swap:

```bash
swapon --show
free -h
```

## Certificates

- API certificate: `/etc/letsencrypt/live/apis.dsdwallet.com/`
- Frontend certificate: `/etc/letsencrypt/live/dsdwallet.com/`

Test both certificates:

```bash
sudo certbot certificates
sudo certbot renew --dry-run
```

## Initial data and scheduled-task setup

Run interactive Django commands with the deployed environment loaded:

```bash
cd /opt/wallet-backend
source .venv/bin/activate
set -a; source .env; set +a
```

Import the 250-country dataset:

```bash
python manage.py import_global_countries /opt/wallet-backend/global_countries.json
```

Register or update all Celery Beat schedules:

```bash
python manage.py seed_periodic_tasks
```

Check wallet ledger reconciliation without changing data:

```bash
python manage.py reconcile_balances
```

Refresh exchange rates manually:

```bash
python manage.py refresh_exchange_rates
```

The exchange-rate provider may reject requests with HTTP 403. If that occurs, configure a permitted provider or API key before retrying. The scheduled task remains registered and Celery Beat will retry according to the configured schedule.

Do not run these automatically without reviewing their effect:

```bash
python manage.py process_scheduled_transfers
python manage.py run_task <task_name>
```

They can execute scheduled financial operations. `create_merchants` requires explicit existing user IDs or email addresses:

```bash
python manage.py create_merchants --email user@example.com --business-name "Business Name"
```

## Frontend API URL

The deployed frontend is built with:

```text
NEXT_PUBLIC_API_BASE_URL=https://apis.dsdwallet.com/api
```

Frontend source configuration is in `/opt/dsd-wallet/.env.production`. Rebuild after changing it:

```bash
cd /opt/dsd-wallet
npm ci
npm run build
sudo systemctl restart dsd-wallet
```

## Merchant payment experience

- Customer merchant lookup and QR scanner: `https://dsdwallet.com/pay`
- Merchant payment page: `https://dsdwallet.com/pay/<merchant-number>`
- Merchant portal QR and assigned number: `https://dsdwallet.com/dashboard/qr` and the dashboard overview
- Merchant settlement UI: `https://dsdwallet.com/dashboard/settlements`

The customer flow verifies the merchant before payment, then reuses the existing payment approval and completion status flow. The browser QR scanner uses the device camera where `BarcodeDetector` is supported; manual merchant-code entry remains available everywhere.

Completed merchant withdrawals now create a `withdrawal` transaction linked to the debit ledger entry. The backend implementation is in `/opt/wallet-backend/wallet/merchant_views.py`.

## CORS configuration

The production frontend origins are configured in `/opt/wallet-backend/.env`:

```text
FRONTEND_ORIGIN=https://dsdwallet.com
CORS_ALLOWED_ORIGINS=https://dsdwallet.com,https://www.dsdwallet.com
CSRF_TRUSTED_ORIGINS=https://dsdwallet.com,https://www.dsdwallet.com,https://apis.dsdwallet.com
```

After changing these values, restart the API services:

```bash
sudo systemctl restart wallet-web wallet-celery wallet-celery-beat
```

Verify a browser-style preflight:

```bash
curl -i -X OPTIONS https://apis.dsdwallet.com/api/me \
  -H "Origin: https://dsdwallet.com" \
  -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization,content-type"
```

The response must include `access-control-allow-origin: https://dsdwallet.com` and `access-control-allow-credentials: true`.

## Normal local-to-server deployment workflow

This section documents the manual deployment procedure used when the changes are
being made in the local checkouts rather than deployed through GitHub Actions.
Run these commands from the developer computer. Do not copy local `.env` files,
Firebase credentials, virtual environments, `node_modules`, build caches, or
database files to the server.

### 1. Set the connection variables

```bash
export DEPLOY_KEY="/Users/tutumelchizedek/Documents/aws/Tutu.pem"
export DEPLOY_HOST="ec2-user@51.21.180.12"
export BACKEND_LOCAL="/Users/tutumelchizedek/Downloads/Wallet-Backend"
export FRONTEND_LOCAL="/Users/tutumelchizedek/Downloads/dsd-wallet"
export BACKEND_REMOTE="/opt/wallet-backend"
export FRONTEND_REMOTE="/opt/dsd-wallet"
```

Verify SSH access before transferring files:

```bash
ssh -i "$DEPLOY_KEY" -o ConnectTimeout=20 "$DEPLOY_HOST" \
  'hostname && systemctl is-active wallet-web dsd-wallet'
```

### 2. Validate locally before copying

Backend:

```bash
cd "$BACKEND_LOCAL"
python3 -m py_compile wallet/admin_views.py wallet/urls.py
```

Frontend:

```bash
cd "$FRONTEND_LOCAL"
npm ci
npm run build -- --webpack
```

Use the smallest relevant test command when the project provides a targeted
test. For a backend configuration check with the local environment available:

```bash
cd "$BACKEND_LOCAL"
python3 manage.py check
```

### 3. Copy the backend to the server

For a complete source update, synchronize the backend while preserving the
server environment, secrets, database, backups, and Python cache:

```bash
rsync -az --delete \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='db.sqlite3' \
  --exclude='backups/' \
  --exclude='secrets/' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  -e "ssh -i $DEPLOY_KEY" \
  "$BACKEND_LOCAL/" "$DEPLOY_HOST:$BACKEND_REMOTE/"
```

For a small surgical change, copy only the changed files. This is safer when
the server has local-only files or when a full source transfer is unnecessary:

```bash
scp -i "$DEPLOY_KEY" \
  "$BACKEND_LOCAL/wallet/admin_views.py" \
  "$BACKEND_LOCAL/wallet/urls.py" \
  "$DEPLOY_HOST:/tmp/"

ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST" \
  "cp /tmp/admin_views.py $BACKEND_REMOTE/wallet/admin_views.py && \
   cp /tmp/urls.py $BACKEND_REMOTE/wallet/urls.py"
```

After copying backend files, validate and restart:

```bash
ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST" "
  set -e
  cd '$BACKEND_REMOTE'
  .venv/bin/python manage.py check
  sudo systemctl restart wallet-web wallet-celery wallet-celery-beat
  systemctl is-active wallet-web wallet-celery wallet-celery-beat
"
```

Run migrations only when the change includes new or altered migrations. Load
the server environment so Django uses the same database credentials as the
systemd service:

```bash
ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST" "
  set -e
  cd '$BACKEND_REMOTE'
  set -a; source .env; set +a
  .venv/bin/python manage.py migrate --noinput
"
```

If a direct migration command reports a PostgreSQL password error, stop and
inspect the service environment rather than changing the database password
blindly. The command must use the same `DATABASE_URL` or database variables as
`wallet-web`.

### 4. Copy and build the merchant frontend

The merchant and customer frontend is the Next.js application in
`/Users/tutumelchizedek/Downloads/dsd-wallet`. Copy source files without
overwriting the server's production environment:

```bash
rsync -az --delete \
  --exclude='.git' \
  --exclude='.env*' \
  --exclude='node_modules/' \
  --exclude='.next/' \
  -e "ssh -i $DEPLOY_KEY" \
  "$FRONTEND_LOCAL/" "$DEPLOY_HOST:$FRONTEND_REMOTE/"
```

Build and restart it on the server:

```bash
ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST" "
  set -e
  cd '$FRONTEND_REMOTE'
  npm ci
  npm run build -- --webpack
  sudo systemctl restart dsd-wallet
  systemctl is-active dsd-wallet
"
```

The production frontend environment remains on the server at
`/opt/dsd-wallet/.env.production`. Changes to `NEXT_PUBLIC_*` values require a
new build because those values are embedded into the browser bundle.

### 5. Verify the deployment

Check every application service:

```bash
ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST" \
  'systemctl is-active nginx dsd-wallet wallet-web wallet-celery wallet-celery-beat'
```

Check public routes:

```bash
curl -fsS -o /dev/null -w 'frontend: %{http_code}\n' \
  https://dsdwallet.com/
curl -fsS -o /dev/null -w 'admin revenue page: %{http_code}\n' \
  https://dsdwallet.com/admin/fee-revenue
curl -fsS -o /dev/null -w 'API schema: %{http_code}\n' \
  https://apis.dsdwallet.com/api/schema/
```

Admin API routes require an authenticated admin session or bearer token. A
`401` response without credentials is expected and confirms that the route is
reachable and protected:

```bash
curl -sS -o /tmp/admin-revenue.json \
  -w 'admin fee API without credentials: %{http_code}\n' \
  'https://apis.dsdwallet.com/api/admin/fee-revenue?time_range=30d'
```

Review recent errors if any check fails:

```bash
ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST" \
  'sudo journalctl -u wallet-web -u dsd-wallet --no-pager -n 100'
```

### 6. Rollback guidance

Before a risky deployment, save the current files or record the current
commit. If the update was deployed from Git:

```bash
ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST" "
  cd '$BACKEND_REMOTE'
  git log -1 --oneline
  git status --short
"
```

For a source transfer, restore the previous known-good checkout or copy back
the specific files from the local backup, then restart only the affected
service:

```bash
ssh -i "$DEPLOY_KEY" "$DEPLOY_HOST" \
  'sudo systemctl restart wallet-web dsd-wallet'
```

Never roll back by deleting `/opt/wallet-backend`, `/opt/dsd-wallet`, the
database, media, `.env`, or the `secrets/` directory.

### 7. GitHub Actions alternative

Both repositories also contain a GitHub Actions deployment workflow. A push to
the configured `main` branch runs validation, synchronizes source with
`rsync`, and invokes the server deployment script. A manual run can be started
from the repository's Actions tab using `workflow_dispatch`.

The workflows require repository secrets for the deployment host, user, SSH
private key, and remote application directories. Keep those values in GitHub
Secrets; do not place them in workflow files or source code. The manual local
workflow above is preferred for a controlled surgical production fix.
