# Operations portal deployment

The operations portal is a separate TypeScript application in this repository.
It must run as its own process and hostname. The Django application keeps
serving `/admin/`; the portal uses normal page routes such as `/overview`,
`/transactions`, and `/reports`.

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
printf 'API_BASE_URL=/api\n' > .env
npm run build
```

The portal authenticates with `POST /api/auth/admin`, stores the returned
short-lived API token in browser storage, and sends it as a Bearer token on
every protected request. The backend still enforces `IsAdminUser` on the
operations APIs.

## 3. Run the portal

```bash
sudo cp deploy/wallet-operations.service \
  /etc/systemd/system/wallet-operations.service
sudo systemctl daemon-reload
sudo systemctl enable --now wallet-operations
```

Confirm the local process:

```bash
curl -I http://127.0.0.1:3100/
```

## 4. Nginx

Assign a DNS record such as `operations.example.com` to the same server IP.
Install the portal server block:

```bash
sudo cp deploy/nginx.operations.conf \
  /etc/nginx/sites-available/operations-portal
sudo ln -s /etc/nginx/sites-available/operations-portal \
  /etc/nginx/sites-enabled/operations-portal
sudo nginx -t
sudo systemctl reload nginx
```

Replace `operations.example.com` in that file with the real hostname.
Do not change the existing Django server block or its `/admin/` location.

## 5. HTTPS and Django settings

```bash
sudo certbot --nginx -d operations.example.com
```

Add the operations origin to Django production settings:

```python
CSRF_TRUSTED_ORIGINS = [
    "https://operations.example.com",
]
```

Use HTTPS for both the portal and API. Do not expose port `3100` publicly;
allow it only on loopback and let Nginx proxy to it.

## 6. Verify authentication

1. Open `https://operations.example.com/user/login`.
2. Sign in with the staff account.
3. Confirm the browser navigates to `/overview`.
4. Confirm `/transactions` loads data.
5. Confirm a non-staff account receives access denied.
6. Confirm clearing the token redirects back to `/user/login`.
7. Confirm Django `/admin/` still opens on the existing application host.

