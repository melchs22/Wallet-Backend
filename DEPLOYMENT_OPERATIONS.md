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
