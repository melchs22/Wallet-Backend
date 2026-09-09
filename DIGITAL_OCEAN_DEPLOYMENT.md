# Digital Ocean Droplet Deployment Guide - Wallet Backend

This guide provides step-by-step instructions to manually deploy the Wallet backend on a Digital Ocean droplet at IP `178.128.156.225` using PostgreSQL database.

## Prerequisites

- Digital Ocean droplet with Ubuntu 22.04 or 24.04
- SSH access to the droplet
- Domain name (optional, recommended for production)
- Google OAuth credentials (for authentication)

## Step 1: Initial Server Setup

### 1.1 Connect to your droplet

```bash
ssh root@178.128.156.225
```

### 1.2 Update system and create user

```bash
# Update system
apt update && apt upgrade -y

# Create a dedicated user for the application
adduser wallet
usermod -aG sudo wallet

# Switch to the new user
su - wallet
```

### 1.3 Configure firewall

```bash
# Configure UFW firewall
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## Step 2: Install Required Packages

```bash
# Install system dependencies
sudo apt update
sudo apt install -y \
    python3-venv \
    python3-dev \
    build-essential \
    libpq-dev \
    postgresql \
    postgresql-contrib \
    redis-server \
    nginx \
    git \
    curl \
    ca-certificates
```

## Step 3: PostgreSQL Setup

### 3.1 Create database and user

```bash
# Switch to postgres user
sudo -u postgres psql
```

Run these SQL commands in the PostgreSQL prompt:

```sql
-- Create a secure password (generate one with: openssl rand -base64 32)
CREATE USER walletapp WITH PASSWORD 'YOUR_SECURE_PASSWORD_HERE';

-- Create database
CREATE DATABASE walletmvp OWNER walletapp;

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE walletmvp TO walletapp;

-- Exit
\q
```

### 3.2 Configure PostgreSQL for remote access (if needed)

If you need remote access to PostgreSQL (not recommended for production):

```bash
sudo nano /etc/postgresql/*/main/postgresql.conf
```

Add/modify:
```
listen_addresses = 'localhost'
```

```bash
sudo nano /etc/postgresql/*/main/pg_hba.conf
```

Ensure this line exists:
```
host    walletmvp    walletapp    127.0.0.1/32    scram-sha-256
```

Restart PostgreSQL:
```bash
sudo systemctl restart postgresql
```

## Step 4: Clone and Setup Backend

### 4.1 Create application directory

```bash
sudo mkdir -p /var/www/backend
sudo chown -R wallet:wallet /var/www
```

### 4.2 Clone repository

```bash
cd /var/www/backend
git clone https://github.com/melchs22/Wallet-Backend.git .
```

### 4.3 Create Python virtual environment

```bash
cd /var/www/backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Step 5: Environment Configuration

### 5.1 Generate secrets

```bash
# Generate Django secret key
DJANGO_SECRET_KEY=$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')

# Generate QR signing secret
QR_SECRET=$(openssl rand -hex 32)

# Display the secrets (save them securely)
echo "Django Secret Key: $DJANGO_SECRET_KEY"
echo "QR Secret: $QR_SECRET"
```

### 5.2 Create .env file

```bash
nano /var/www/backend/.env
```

Add the following configuration:

```env
DJANGO_SETTINGS_MODULE=walletmvp.settings
SECRET_KEY=YOUR_DJANGO_SECRET_KEY_HERE
DEBUG=False
ALLOWED_HOSTS=178.128.156.225,localhost,127.0.0.1

# PostgreSQL Database
DATABASE_URL=postgresql://walletapp:YOUR_SECURE_PASSWORD@127.0.0.1:5432/walletmvp
DB_CONN_MAX_AGE=60

# Frontend Configuration
FRONTEND_ORIGIN=http://178.128.156.225
FRONTEND_ORIGIN_URL=http://178.128.156.225
CORS_ALLOWED_ORIGINS=http://178.128.156.225
CSRF_TRUSTED_ORIGINS=http://178.128.156.225

# Session/Cookie Configuration
SESSION_COOKIE_SECURE=False
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SECURE=False
CSRF_COOKIE_SAMESITE=Lax

# Google OAuth (get from https://console.cloud.google.com)
GOOGLE_CLIENT_ID=your-google-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret

# QR Code Security
QR_SIGNING_SECRET=YOUR_QR_SECRET_HERE

# Redis Configuration
REDIS_URL=redis://127.0.0.1:6379/0
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
```

### 5.3 Secure the .env file

```bash
chmod 600 /var/www/backend/.env
```

## Step 6: Database Migration

### 6.1 Run Django migrations

```bash
cd /var/www/backend
source .venv/bin/activate
set -a; source .env; set +a

# Run migrations
python manage.py migrate --noinput

# Collect static files
python manage.py collectstatic --noinput

# Create superuser (optional)
python manage.py createsuperuser
```

### 6.2 Verify database connection

```bash
python manage.py check --deploy
```

## Step 7: SQLite to PostgreSQL Migration (if you have existing data)

If you have existing SQLite data you want to migrate:

### 7.1 Export SQLite data (on your local machine)

```bash
cd /path/to/local/Wallet-Backend
python manage.py dumpdata --natural-foreign --natural-primary > sqlite_backup.json
```

### 7.2 Transfer to server

```bash
scp sqlite_backup.json wallet@178.128.156.225:/var/www/backend/
```

### 7.3 Import to PostgreSQL (on server)

```bash
cd /var/www/backend
source .venv/bin/activate
set -a; source .env; set +a

python manage.py loaddata sqlite_backup.json
```

## Step 8: Systemd Services

### 8.1 Create Django Gunicorn service

```bash
sudo nano /etc/systemd/system/wallet-web.service
```

Add:

```ini
[Unit]
Description=Wallet Django API
After=network.target postgresql.service redis-server.service

[Service]
User=wallet
Group=wallet
WorkingDirectory=/var/www/backend
EnvironmentFile=/var/www/backend/.env
ExecStart=/var/www/backend/.venv/bin/gunicorn walletmvp.wsgi:application \
    --bind 127.0.0.1:8000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
Restart=always

[Install]
WantedBy=multi-user.target
```

### 8.2 Create Celery worker service

```bash
sudo nano /etc/systemd/system/wallet-celery.service
```

Add:

```ini
[Unit]
Description=Wallet Celery Worker
After=network.target redis-server.service postgresql.service

[Service]
User=wallet
Group=wallet
WorkingDirectory=/var/www/backend
EnvironmentFile=/var/www/backend/.env
ExecStart=/var/www/backend/.venv/bin/celery -A walletmvp worker \
    -l info \
    --concurrency=2
Restart=always

[Install]
WantedBy=multi-user.target
```

### 8.3 Create Celery Beat service

```bash
sudo nano /etc/systemd/system/wallet-celery-beat.service
```

Add:

```ini
[Unit]
Description=Wallet Celery Beat
After=network.target redis-server.service postgresql.service

[Service]
User=wallet
Group=wallet
WorkingDirectory=/var/www/backend
EnvironmentFile=/var/www/backend/.env
ExecStart=/var/www/backend/.venv/bin/celery -A walletmvp beat \
    -l info \
    --scheduler django_celery_beat.schedulers:DatabaseScheduler
Restart=always

[Install]
WantedBy=multi-user.target
```

### 8.4 Enable and start services

```bash
sudo systemctl daemon-reload
sudo systemctl enable wallet-web wallet-celery wallet-celery-beat
sudo systemctl start wallet-web wallet-celery wallet-celery-beat

# Check status
sudo systemctl status wallet-web --no-pager
sudo systemctl status wallet-celery --no-pager
sudo systemctl status wallet-celery-beat --no-pager
```

## Step 9: Nginx Configuration

### 9.1 Create Nginx configuration

```bash
sudo nano /etc/nginx/sites-available/wallet
```

Add:

```nginx
server {
    listen 80;
    server_name 178.128.156.225;

    # Increase upload size for file uploads
    client_max_body_size 10M;

    # Static files
    location /static/ {
        alias /var/www/backend/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Media files
    location /media/ {
        alias /var/www/backend/media/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # API proxy
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }

    # Health check endpoint
    location /health/ {
        proxy_pass http://127.0.0.1:8000/health/;
        access_log off;
    }
}
```

### 9.2 Enable configuration

```bash
sudo ln -s /etc/nginx/sites-available/wallet /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

## Step 10: Redis Configuration

### 10.1 Configure Redis for production

```bash
sudo nano /etc/redis/redis.conf
```

Set these parameters:

```
bind 127.0.0.1
maxmemory 256mb
maxmemory-policy allkeys-lru
save ""
```

### 10.2 Restart Redis

```bash
sudo systemctl restart redis-server
sudo systemctl enable redis-server
```

## Step 11: Verify Deployment

### 11.1 Check API health

```bash
curl http://178.128.156.225/api/
curl http://178.128.156.225/health/
```

### 11.2 Check logs

```bash
# Django logs
sudo journalctl -u wallet-web -f

# Celery logs
sudo journalctl -u wallet-celery -f

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### 11.3 Test database connection

```bash
cd /var/www/backend
source .venv/bin/activate
set -a; source .env; set +a
python manage.py dbshell
```

## Step 12: SSL/HTTPS Setup (Recommended for Production)

### 12.1 Install Certbot

```bash
sudo apt install certbot python3-certbot-nginx
```

### 12.2 Obtain SSL certificate

Replace `yourdomain.com` with your actual domain:

```bash
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

### 12.3 Update .env for HTTPS

```bash
nano /var/www/backend/.env
```

Change these values:

```env
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
CSRF_COOKIE_SAMESITE=Strict
```

Update allowed hosts and origins:

```env
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,178.128.156.225
FRONTEND_ORIGIN=https://yourdomain.com
FRONTEND_ORIGIN_URL=https://yourdomain.com
CORS_ALLOWED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

### 12.4 Restart services

```bash
sudo systemctl restart wallet-web wallet-celery wallet-celery-beat
```

## Step 13: Backup Setup

### 13.1 Create backup script

```bash
sudo nano /usr/local/bin/backup-wallet.sh
```

Add:

```bash
#!/bin/bash
BACKUP_DIR="/opt/backups"
DATE=$(date +%Y%m%d-%H%M)
mkdir -p "$BACKUP_DIR"

# Backup PostgreSQL
pg_dump -U walletapp -h 127.0.0.1 walletmvp | gzip > "$BACKUP_DIR/walletmvp-$DATE.sql.gz"

# Keep only last 7 days
find "$BACKUP_DIR" -name "walletmvp-*.sql.gz" -mtime +7 -delete

echo "Backup completed: $BACKUP_DIR/walletmvp-$DATE.sql.gz"
```

Make executable:

```bash
sudo chmod +x /usr/local/bin/backup-wallet.sh
```

### 13.2 Setup cron job

```bash
crontab -e
```

Add daily backup at 2 AM:

```
0 2 * * * /usr/local/bin/backup-wallet.sh
```

## Step 14: Monitoring and Maintenance

### 14.1 Install monitoring tools (optional)

```bash
sudo apt install htop iotop
```

### 14.2 Setup log rotation

```bash
sudo nano /etc/logrotate.d/wallet
```

Add:

```
/var/log/wallet/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 wallet wallet
    sharedscripts
}
```

## Troubleshooting

### Common Issues

**Database connection error:**
```bash
# Check PostgreSQL status
sudo systemctl status postgresql

# Check connection
psql -U walletapp -h 127.0.0.1 -d walletmvp
```

**Celery not working:**
```bash
# Check Redis
sudo systemctl status redis-server
redis-cli ping

# Check Celery logs
sudo journalctl -u wallet-celery -n 50
```

**Nginx 502 error:**
```bash
# Check if Gunicorn is running
sudo systemctl status wallet-web

# Check Gunicorn can bind to port
netstat -tlnp | grep 8000
```

**Static files not loading:**
```bash
# Recollect static files
cd /var/www/backend
source .venv/bin/activate
set -a; source .env; set +a
python manage.py collectstatic --noinput --clear

# Check permissions
sudo chown -R wallet:wallet /var/www/backend/staticfiles
```

## Security Checklist

Before going to production:

- [ ] Change all default passwords
- [ ] Enable HTTPS with valid SSL certificate
- [ ] Set `DEBUG=False` in .env
- [ ] Configure firewall properly
- [ ] Restrict PostgreSQL to localhost only
- [ ] Set up regular backups
- [ ] Monitor logs regularly
- [ ] Keep system packages updated
- [ ] Use strong secrets for all environment variables
- [ ] Configure fail2ban for SSH protection
- [ ] Set up monitoring and alerts

## API Endpoints

After deployment, your API will be available at:

- API Base: `http://178.128.156.225/api/`
- API Docs: `http://178.128.156.225/api/docs/`
- Admin: `http://178.128.156.225/admin/`
- Health Check: `http://178.128.156.225/health/`

## Next Steps

1. Deploy your Flutter app with the new API URL
2. Configure Google OAuth with the correct redirect URIs
3. Set up CI/CD pipeline for automated deployments
4. Configure monitoring and alerting
5. Set up staging environment for testing

## Support

For issues or questions:
- Check logs: `sudo journalctl -u wallet-web -f`
- Django documentation: https://docs.djangoproject.com/
- Digital Ocean docs: https://docs.digitalocean.com/
