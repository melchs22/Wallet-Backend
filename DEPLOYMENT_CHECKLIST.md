# PythonAnywhere Deployment Checklist

Use this checklist to deploy all fixes to PythonAnywhere in the correct order.

## Pre-Deployment

- [ ] Backup current PythonAnywhere deployment
- [ ] Note down current environment variables
- [ ] Have local files ready to upload

## Step 1: Upload Updated Files

Upload these files from `/Users/tutumelchizedek/Downloads/Wallet App/` to PythonAnywhere `/home/TECH212/mysite/`:

- [ ] `walletmvp/settings.py` - Session, auth, static files configuration
- [ ] `wallet/views.py` - OAuth redirect URI fix, session save enforcement
- [ ] `wallet/urls.py` - URL pattern reordering
- [ ] `collect_static.sh` - New script for collecting static files
- [ ] `debug_session.py` - New debug script for troubleshooting
- [ ] `static/` - New directory (create if doesn't exist)

## Step 2: Update Environment Variables

In PythonAnywhere `/home/TECH212/mysite/.env`, ensure these are set:

```env
# Database
DATABASE_URL=postgresql://TECH212:password@TECH212.postgres.pythonanywhere-services.com/TECH212

# Django
SECRET_KEY=your-generated-secret-key
DEBUG=False
ALLOWED_HOSTS=TECH212.pythonanywhere.com,www.TECH212.pythonanywhere.com

# CORS
FRONTEND_ORIGIN=https://dsd-wallet.vercel.app

# Session Security (CRITICAL)
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SESSION_COOKIE_SAMESITE=None
CSRF_COOKIE_SAMESITE=None
CSRF_TRUSTED_ORIGINS=https://dsd-wallet.vercel.app
SESSION_COOKIE_AGE=2592000

# Google OAuth
GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=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
```

- [ ] DATABASE_URL set correctly
- [ ] SECRET_KEY is unique and secure
- [ ] DEBUG=False
- [ ] ALLOWED_HOSTS includes TECH212.pythonanywhere.com
- [ ] FRONTEND_ORIGIN=https://dsd-wallet.vercel.app
- [ ] SESSION_COOKIE_SECURE=True
- [ ] CSRF_COOKIE_SECURE=True
- [ ] SESSION_COOKIE_SAMESITE=None
- [ ] CSRF_COOKIE_SAMESITE=None
- [ ] CSRF_TRUSTED_ORIGINS=https://dsd-wallet.vercel.app
- [ ] SESSION_COOKIE_AGE=2592000
- [ ] Google OAuth credentials set

## Step 3: Configure Static Files Mapping

In PythonAnywhere Dashboard → Web → my_web_app → Static files:

- [ ] URL: `/static/`
- [ ] Directory: `/home/TECH212/mysite/staticfiles/`

## Step 4: Run Database Migrations

```bash
cd ~/mysite
source venv/bin/activate
python manage.py migrate
```

- [ ] Migrations completed successfully
- [ ] No errors during migration

## Step 5: Collect Static Files

```bash
cd ~/mysite
source venv/bin/activate
python manage.py collectstatic --noinput --clear
```

Or use the script:
```bash
cd ~/mysite
./collect_static.sh
```

- [ ] Static files collected successfully
- [ ] `staticfiles/` directory created
- [ ] No errors during collection

## Step 6: Run Debug Script

```bash
cd ~/mysite
source venv/bin/activate
python debug_session.py
```

- [ ] Debug script runs successfully
- [ ] All settings are correct (no warnings)
- [ ] Session database is accessible

## Step 7: Reload Web Application

In PythonAnywhere Dashboard → Web → my_web_app:
- [ ] Click "Reload" button
- [ ] Wait for reload to complete
- [ ] Check that status is "Running"

## Step 8: Test Django Admin

- [ ] Visit `https://TECH212.pythonanywhere.com/admin/`
- [ ] Admin UI loads with proper styling (no 404 errors)
- [ ] Can login with superuser credentials
- [ ] Admin dashboard is accessible

## Step 9: Test OAuth Flow

- [ ] Visit `https://dsd-wallet.vercel.app/login`
- [ ] Click "Continue with Google"
- [ ] Google OAuth completes successfully
- [ ] Redirected to `/auth/callback`
- [ ] `/api/auth/google` returns 200 OK (check network tab)
- [ ] Session cookie is set (check Application → Cookies)

## Step 10: Test Authenticated Endpoints

After successful login:

- [ ] `GET /api/me` returns 200 OK with user data
- [ ] `GET /api/wallet` returns 200 OK with wallet data
- [ ] `GET /api/notifications` returns 200 OK with notifications
- [ ] `GET /api/transactions` returns 200 OK with transactions
- [ ] No 403 Forbidden errors

## Step 11: Test Session Persistence

- [ ] Close browser
- [ ] Reopen browser
- [ ] Visit `https://dsd-wallet.vercel.app/home`
- [ ] Still logged in (no need to re-authenticate)
- [ ] Session cookie is still present

## Step 12: Check PythonAnywhere Logs

In PythonAnywhere Dashboard → Web → my_web_app → Log files:

- [ ] No 500 Internal Server Errors
- [ ] No session-related errors
- [ ] No CORS errors
- [ ] No authentication errors

## Troubleshooting

If any step fails:

1. **Check error logs** in PythonAnywhere
2. **Run debug script** to verify configuration
3. **Verify environment variables** are set correctly
4. **Check that static files** were collected
5. **Verify static files mapping** in dashboard
6. **Test with local backend** to isolate the issue

## Post-Deployment Verification

After completing all steps:

- [ ] Users can log in with Google OAuth
- [ ] Users stay logged in across browser sessions
- [ ] Users can access all authenticated endpoints
- [ ] Django admin loads correctly with styling
- [ ] No 403 Forbidden errors after login
- [ ] No 404 errors for static files
- [ ] Session cookies are being set correctly
- [ ] CORS is working for cross-origin requests

## Rollback Plan

If deployment causes issues:

1. Restore previous version of files
2. Restore previous environment variables
3. Reload web application
4. Contact support if needed

## Notes

- The local backend at `/Users/tutumelchizedek/Downloads/Wallet App/` has all fixes applied
- PythonAnywhere at `TECH212.pythonanywhere.com` needs these same fixes deployed
- All configuration files have been updated with production values
- Debug scripts are provided for troubleshooting
- Documentation is available in `.md` files
