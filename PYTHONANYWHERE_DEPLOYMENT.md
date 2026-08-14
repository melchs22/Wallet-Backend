# PythonAnywhere Deployment Guide for Wallet MVP Backend

This guide walks you through deploying the Wallet MVP Django backend to PythonAnywhere.

## Prerequisites

- PythonAnywhere account (free or paid)
- Django backend project from `/Users/tutumelchizedek/Downloads/Wallet App/`
- Google Cloud Console project with OAuth credentials
- PostgreSQL database (recommended) or SQLite for testing

## Step 1: Upload Your Project to PythonAnywhere

### Option A: Using Git (Recommended)

1. Initialize git in your local project:
```bash
cd "/Users/tutumelchizedek/Downloads/Wallet App"
git init
git add .
git commit -m "Initial commit"
```

2. Create a GitHub repository and push your code
3. In PythonAnywhere, use the "Git" option to clone your repository

### Option B: Using Manual Upload

1. In PythonAnywhere, go to "Files" → "mysite"
2. Upload your project files using the web interface
3. Ensure the file structure matches your local project

## Step 2: Configure Python Environment

1. In PythonAnywhere, go to "Web" → "my_web_app"
2. Under "Code", create a virtual environment:
   - Click "Run a virtualenv setup" (if not already created)
   - Python version: 3.14 (or latest available)
   - Virtualenv name: `venv`

3. Install dependencies:
```bash
source ~/mysite/venv/bin/activate
cd ~/mysite
pip install -r requirements.txt
```

## Step 3: Set Up PostgreSQL Database

### Create PostgreSQL Database

1. In PythonAnywhere, go to "Databases"
2. Click "Start a new PostgreSQL server"
3. Set a strong password and save it
4. Note the database name (usually your username)
5. Note the host (usually `username.postgres.pythonanywhere-services.com`)

### Configure Django to Use PostgreSQL

1. Update your `.env` file with the PostgreSQL connection string:
```env
DATABASE_URL=postgresql://username:password@username.postgres.pythonanywhere-services.com/username
```

2. For local development, keep using SQLite:
```env
# Local development
DATABASE_URL=sqlite:///db.sqlite3
```

## Step 4: Configure Environment Variables

### Create `.env` File

1. In PythonAnywhere, go to "Files" → "mysite"
2. Create a `.env` file with your production variables:

```env
# Database
DATABASE_URL=postgresql://username:password@username.postgres.pythonanywhere-services.com/username

# Django Settings
SECRET_KEY=your-production-secret-key-generate-with-python
DEBUG=False
ALLOWED_HOSTS=TECH212.pythonanywhere.com,www.TECH212.pythonanywhere.com
FRONTEND_ORIGIN=https://dsd-wallet.vercel.app
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SESSION_COOKIE_SAMESITE=None
CSRF_COOKIE_SAMESITE=None
CSRF_TRUSTED_ORIGINS=https://dsd-wallet.vercel.app

# Google OAuth
GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=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
```

### Generate SECRET_KEY

Run this command to generate a secure secret key:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## Step 5: Configure Django Settings

### Update `walletmvp/settings.py`

1. Add your PythonAnywhere domain to `ALLOWED_HOSTS`:
```python
ALLOWED_HOSTS = [
    'TECH212.pythonanywhere.com',
    'www.TECH212.pythonanywhere.com',
]
```

2. Update `FRONTEND_ORIGIN`:
```python
FRONTEND_ORIGIN = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:3000')
```

3. Ensure these are set for production:
```python
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', 'True') == 'True'
CSRF_COOKIE_SECURE = os.environ.get('CSRF_COOKIE_SECURE', 'True') == 'True'
```

## Step 6: Configure WSGI File

### Create or Update `mysite/wsgi.py`

1. In PythonAnywhere, go to "Files" → "mysite"
2. Create `mysite/wsgi.py`:
```python
import os
import sys
from django.core.wsgi import get_wsgi_application

# Add the project directory to the Python path
sys.path.insert(0, '/home/TECH212/mysite')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'walletmvp.settings')

application = get_wsgi_application()
```

## Step 7: Configure Web Application

### Update WSGI Configuration File

1. In PythonAnywhere, go to "Web" → "my_web_app"
2. Click on the "WSGI configuration file" link
3. Update the file to point to your Django project:
```python
import os
import sys
from django.core.wsgi import get_wsgi_application

# Add the project directory to the Python path
sys.path.insert(0, '/home/TECH212/mysite')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'walletmvp.settings')

application = get_wsgi_application()
```

### Update Static Files

1. In "Web" → "my_web_app", scroll to "Static files"
2. Configure static file mapping:
   - URL: `/static/`
   - Directory: `/home/TECH212/mysite/staticfiles/`

3. In your Django `settings.py`, ensure:
```python
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
```

### Run Static Files Collection

```bash
source ~/mysite/venv/bin/activate
cd ~/mysite
python manage.py collectstatic --noinput --clear
```

**Or use the provided script:**
```bash
cd ~/mysite
./collect_static.sh
```

## Step 8: Run Database Migrations

```bash
source ~/mysite/venv/bin/activate
cd ~/mysite
python manage.py migrate
```

## Step 9: Create Superuser (Optional)

```bash
source ~/mysite/venv/bin/activate
cd ~/mysite
python manage.py createsuperuser
```

## Step 10: Configure Google OAuth for Production

### Update Google Cloud Console

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project
3. Go to "APIs & Services" → "Credentials"
4. Edit your OAuth 2.0 client ID
5. Add authorized redirect URIs:
   - `https://dsd-wallet.vercel.app/auth/callback`
   - `https://TECH212.pythonanywhere.com/auth/callback` (for testing)
6. Save changes

### Update Environment Variables

Ensure your `.env` file has the production credentials:
```env
GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=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
```

## Step 11: Configure CORS

### Update `walletmvp/settings.py`

```python
CORS_ALLOWED_ORIGINS = [
    "https://dsd-wallet.vercel.app",
    "http://localhost:3000",  # For local development
]
```

## Step 12: Configure Allowed Hosts

### Update Django Settings

In your `.env` file or `settings.py`:
```python
ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')
```

Set the environment variable:
```env
ALLOWED_HOSTS=TECH212.pythonanywhere.com,www.TECH212.pythonanywhere.com
```

## Step 13: Test the Deployment

1. Reload your web application in PythonAnywhere
2. Visit `https://TECH212.pythonanywhere.com/api/me`
3. You should see a 401 response (authenticated only)
4. Visit `https://TECH212.pythonanywhere.com/api/schema/` to see OpenAPI documentation

## Step 14: Configure Frontend for Production

### Update Frontend Environment Variables

In your Vercel deployment, set:
```env
NEXT_PUBLIC_API_BASE_URL=https://TECH212.pythonanywhere.com/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
```

### Test the Connection

1. Visit `https://dsd-wallet.vercel.app/login`
2. Click "Continue with Google"
3. You should be redirected to Google OAuth
4. After authentication, you should be redirected back to the app

## Step 15: Set Up Scheduled Tasks (Optional)

### Balance Reconciliation Job

1. In PythonAnywhere, go to "Tasks"
2. Create a scheduled task:
   - Command: `/home/TECH212/mysite/venv/bin/python /home/TECH212/mysite/manage.py reconcile_balances`
   - Schedule: Daily (e.g., every day at 2 AM)
   - Description: "Balance reconciliation"
   - Email on success: your email
   - Email on failure: your email

## Step 16: Configure Logging (Optional)

### Set Up Application Logging

1. In `walletmvp/settings.py`, add logging configuration:
```python
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': '/home/TECH212/mysite/logs/django.log',
        },
    },
    'root': {
        'handlers': ['file'],
        'level': 'INFO',
    },
}
```

2. Create the logs directory:
```bash
mkdir -p ~/mysite/logs
```

## Step 17: Security Considerations

### HTTPS Configuration

- PythonAnywhere provides SSL certificates automatically
- Ensure all cookies are set to `Secure=True` in production
- Ensure `SESSION_COOKIE_SECURE=True` and `CSRF_COOKIE_SECURE=True`

### Database Security

- Use strong PostgreSQL password
- Never commit `.env` file to version control
- Use environment variables for all sensitive data

### API Security

- The API uses session-based authentication (httpOnly cookies)
- CORS is restricted to your frontend domain
- CSRF protection is enabled for all state-changing requests

## Step 18: Monitoring and Maintenance

### Check Logs Regularly

1. In PythonAnywhere, go to "Web" → "my_web_app" → "Log files"
2. Monitor for errors and unusual activity

### Monitor Database

1. Go to "Databases" in PythonAnywhere
2. Check disk usage and connection count

### Balance Reconciliation

Run the reconciliation job regularly to detect any ledger drift:
```bash
python manage.py reconcile_balances
```

## Troubleshooting

### 502 Bad Gateway

- Check if the web application is running
- Check the error logs in PythonAnywhere
- Ensure all dependencies are installed

### 403 Forbidden

- Check CORS configuration
- Verify frontend origin is in `CORS_ALLOWED_ORIGINS`
- Check CSRF token configuration

### Database Connection Errors

- Verify DATABASE_URL is correct
- Check PostgreSQL server is running
- Ensure database user has proper permissions

### Migration Errors

- Run `python manage.py makemigrations --check` to see if migrations are missing
- Run `python manage.py migrate` to apply pending migrations

## Production Checklist

- [ ] PostgreSQL database configured
- [ ] Environment variables set (`.env` file)
- [ ] Google OAuth credentials configured for production
- [ ] CORS configured for frontend domain
- [ ] Allowed hosts configured
- [ ] Static files collected
- [ ] Migrations run
- [ ] Superuser created
- [ ] WSGI configuration updated
- [ ] Web application reloaded
- [ ] SSL/HTTPS working
- [ ] Balance reconciliation job scheduled
- [ ] Logging configured
- [ ] Frontend API base URL updated

## Cost Considerations

### PythonAnywhere Free Tier

- PostgreSQL: Free tier includes one database
- Web worker: Free tier includes one worker
- Storage: 512MB included
- Bandwidth: Limited but sufficient for MVP

### Paid Tier Recommendations

If you scale up:
- Consider multiple web workers for high traffic
- Upgrade to paid PostgreSQL for more connections
- Increase storage if you need more than 512MB

## Backup Strategy

### Database Backups

PythonAnywhere automatically backs up PostgreSQL databases. Check your backup schedule in the "Databases" section.

### Code Backups

- Keep your code in a Git repository
- Regularly push changes to GitHub
- This provides version control and backup

## Further Reading

- [PythonAnywhere Documentation](https://help.pythonanywhere.com/)
- [Django Deployment Guide](https://docs.djangoproject.com/en/stable/howto/deployment/)
- [PostgreSQL on PythonAnywhere](https://help.pythonanywhere.com/pages/postgresql/)

## Support

If you encounter issues:
1. Check PythonAnywhere error logs
2. Verify all environment variables are set correctly
3. Ensure all dependencies are installed
4. Test with SQLite locally to isolate database issues
5. Check Google OAuth configuration in Google Cloud Console

## Next Steps

Once deployed:
1. Test the full user flow from frontend to backend
2. Monitor the first few days for any issues
3. Set up log aggregation for production monitoring
4. Consider setting up error tracking (e.g., Sentry)
5. Plan for scaling as user base grows
