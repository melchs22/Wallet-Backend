# Operations portal deployment

The operations portal is a separate TypeScript application in this repository.
It is deployed as static files by Nginx at `/operations/`. The Django
application keeps serving `/`, `/api/`, and `/admin/`; the portal uses normal
page routes such as `/operations/overview`, `/operations/transactions`, and
`/operations/reports`.

## 1. Create an admin user

Run this from the backend root with a unique production password:

```bash
cd /var/www/backend/Wallet-Backend
source .venv/bin/activate
python manage.py create_admin \
  --username operations \
  --email operations@example.com \
  --password 'REPLACE_WITH_A_LONG_RANDOM_PASSWORD'
```

The command marks the account as staff and requires a password change after
the first successful login.

## 2. Build the portal

```bash
cd /var/www/backend/Wallet-Backend/operations-portal
npm ci
printf 'API_BASE_URL=/api\nOPERATIONS_PUBLIC_PATH=/operations/\n' > .env
OPERATIONS_PUBLIC_PATH=/operations/ npm run build
```

The portal authenticates with `POST /api/auth/admin`, stores the returned
short-lived API token in browser storage, and sends it as a Bearer token on
every protected request. The backend still enforces `IsAdminUser` on the
operations APIs.

## 3. Nginx

Install the portal server block:

```bash
sudo cp deploy/nginx.operations.conf \
  /etc/nginx/sites-available/operations-portal
sudo nginx -t
sudo systemctl reload nginx
```

The configuration serves the portal from the existing port 80 server at
`http://178.128.156.225/operations/user/login`. It does not expose a Node,
Umi, or preview port.

## 4. HTTPS and Django settings

```bash
sudo certbot --nginx -d your-domain.example
```

Add the operations origin to Django production settings:

```python
CSRF_TRUSTED_ORIGINS = [
    "https://your-domain.example",
]
```

Use HTTPS for both the portal and API. No frontend application port is needed
in production.

## 5. Verify authentication

1. Open `http://178.128.156.225/operations/user/login`.
2. Sign in with the staff account.
3. Confirm the browser navigates to `/overview`.
4. Confirm `/transactions` loads data.
5. Confirm a non-staff account receives access denied.
6. Confirm clearing the token redirects back to `/user/login`.
7. Confirm Django `/admin/` still opens at `http://178.128.156.225/admin/`.
