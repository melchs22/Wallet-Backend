# 403 Forbidden Errors - Complete Troubleshooting Guide

## Current Situation

Users are still getting 403 Forbidden errors even after updating `.env`. This indicates the changes haven't taken effect.

## Step-by-Step Troubleshooting

### Step 1: Verify .env Changes Were Saved

On PythonAnywhere, run:
```bash
cat ~/Wallet-Backend/.env
```

**Expected output should include:**
```env
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SESSION_COOKIE_SAMESITE=None
CSRF_COOKIE_SAMESITE=None
CSRF_TRUSTED_ORIGINS=https://dsd-wallet.vercel.app
```

**If you still see:**
```env
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SESSION_COOKIE_SAMESITE=Lax
```

Then the `.env` file wasn't saved correctly. Re-edit it and save again.

### Step 2: Verify settings.py Was Updated

On PythonAnywhere, run:
```bash
cd ~/Wallet-Backend
grep -A 5 "SESSION_COOKIE_SAMESITE" walletmvp/settings.py
```

**Expected output:**
```python
SESSION_COOKIE_SAMESITE = env('SESSION_COOKIE_SAMESITE', default='Lax')
```

But more importantly, check if `FRONTEND_ORIGIN_URL` exists:
```bash
grep "FRONTEND_ORIGIN_URL" walletmvp/settings.py
```

**Expected output:**
```python
FRONTEND_ORIGIN_URL = env('FRONTEND_ORIGIN', default='http://localhost:3000')
if isinstance(FRONTEND_ORIGIN_URL, list):
    FRONTEND_ORIGIN_URL = FRONTEND_ORIGIN_URL[0] if FRONTEND_ORIGIN_URL else 'http://localhost:3000'
```

**If not found:** You need to upload the updated `walletmvp/settings.py` from your local machine.

### Step 3: Verify views.py Was Updated

On PythonAnywhere, run:
```bash
cd ~/Wallet-Backend
grep -A 3 "request.session.save()" wallet/views.py
```

**Expected output:**
```python
response = Response(response_data, status=status.HTTP_200_OK)
request.session.save()
return response
```

**If not found:** You need to upload the updated `wallet/views.py` from your local machine.

### Step 4: Verify Web Application Was Reloaded

This is the MOST COMMON issue. Django only reads `.env` on startup.

**In PythonAnywhere Dashboard:**
1. Go to Web → my_web_app
2. Click the "Reload" button
3. Wait for reload to complete
4. Check that status shows "Running"

**After reload, check logs:**
- Web → my_web_app → Log files → Server log
- Look for startup messages that show settings being loaded

### Step 5: Run Debug Script Again

After reload, run:
```bash
cd ~/Wallet-Backend
source venv/bin/activate
python debug_session.py
```

**Expected output:**
```
SESSION_COOKIE_SECURE: True
CSRF_COOKIE_SECURE: True
SESSION_COOKIE_SAMESITE: None
CSRF_COOKIE_SAMESITE: None
CSRF_TRUSTED_ORIGINS: ['https://dsd-wallet.vercel.app']
FRONTEND_ORIGIN: https://dsd-wallet.vercel.app
FRONTEND_ORIGIN_URL: https://dsd-wallet.vercel.app

✅ All settings look correct!
```

**If still showing:**
```
SESSION_COOKIE_SECURE: False
SESSION_COOKIE_SAMESITE: Lax
```

Then the web application wasn't reloaded or the `.env` wasn't saved.

### Step 6: Check Static Files

Static files 404 errors indicate they weren't collected.

**Run:**
```bash
cd ~/Wallet-Backend
ls -la staticfiles/
```

**Expected output:**
```
drwxr-xr-x  2 TECH212 www-data 4096 Aug 14 12:00 admin
drwxr-xr-x  2 TECH212 www-data 4096 Aug 14 12:00 rest_framework
drwxr-xr-x  2 TECH212 www-data 4096 Aug 14 12:00 drf_spectacular
```

**If directory doesn't exist or is empty:**
```bash
source venv/bin/activate
python manage.py collectstatic --noinput --clear
```

### Step 7: Verify Static Files Mapping in PythonAnywhere

**In PythonAnywhere Dashboard:**
1. Go to Web → my_web_app
2. Scroll to "Static files" section
3. Check if this mapping exists:
   - URL: `/static/`
   - Directory: `/home/TECH212/Wallet-Backend/staticfiles`

**If not present:**
1. Click "Add a new static files entry"
2. URL: `/static/`
3. Directory: `/home/TECH212/Wallet-Backend/staticfiles`

### Step 8: Test OAuth Flow Manually

Use curl to test the OAuth endpoint:

```bash
curl -X POST https://TECH212.pythonanywhere.com/api/auth/google \
  -H "Content-Type: application/json" \
  -d '{"code":"test","state":"test"}'
```

**Expected:** 400 Bad Request (invalid code, but not 500 error)

**If 500 error:** The OAuth redirect URI is still broken (views.py not updated)

### Step 9: Check Browser Console

1. Open https://dsd-wallet.vercel.app/login
2. Open browser developer tools (F12)
3. Go to Network tab
4. Click "Continue with Google"
5. Look at the `/api/auth/google` request
6. Check the Response tab

**If 500 error:** Views.py not updated
**If 403 error:** Session not being created/recognized
**If 200 OK:** OAuth works, check for session cookie

### Step 10: Check Session Cookie in Browser

After successful OAuth:

1. Go to Application → Cookies
2. Look for `sessionid` cookie
3. Check the attributes:
   - Domain: Should be `.pythonanywhere.com` or the specific domain
   - Secure: Should be checked
   - SameSite: Should be "None" or not set
   - HttpOnly: Should be checked

**If cookie not present:** Session wasn't created or wasn't sent to frontend

## Most Likely Issues

Based on the logs, here are the most likely issues in order:

### Issue 1: Web Application Not Reloaded (80% likely)

Django only reads `.env` on startup. If you edited `.env` but didn't reload, the old settings are still active.

**Fix:** Reload the web application in PythonAnywhere dashboard.

### Issue 2: Updated Files Not Uploaded (15% likely)

The `settings.py` and `views.py` with the fixes weren't uploaded to PythonAnywhere.

**Fix:** Upload these files from your local machine:
- `/Users/tutumelchizedek/Downloads/Wallet App/walletmvp/settings.py`
- `/Users/tutumelizedek/Downloads/Wallet App/wallet/views.py`
- `/Users/tutumelizedek/Downloads/Wallet App/wallet/urls.py`

### Issue 3: Static Files Not Collected (5% likely)

Static files weren't collected or the mapping isn't configured.

**Fix:** Run `collectstatic` and configure static files mapping.

## Complete Fix Sequence

### On PythonAnywhere, run these commands in order:

```bash
# 1. Go to project directory
cd ~/Wallet-Backend

# 2. Edit .env file
nano .env
# Replace entire content with the corrected version
# Save and exit (Ctrl+O, Enter, Ctrl+X)

# 3. Upload updated files (do this from your local machine)
# Upload: walletmvp/settings.py
# Upload: wallet/views.py
# Upload: wallet/urls.py

# 4. Activate virtual environment
source venv/bin/activate

# 5. Run migrations
python manage.py migrate

# 6. Collect static files
python manage.py collectstatic --noinput --clear

# 7. Run debug script
python debug_session.py

# 8. In PythonAnywhere dashboard, reload web application
```

## Verification

After completing all steps:

### Debug Script Should Show:
```
SESSION_COOKIE_SECURE: True
CSRF_COOKIE_SECURE: True
SESSION_COOKIE_SAMESITE: None
CSRF_COOKIE_SAMESITE: None
FRONTEND_ORIGIN: https://dsd-wallet.vercel.app
✅ All settings look correct!
```

### Browser Should:
- ✅ OAuth completes with 200 OK
- ✅ Session cookie is set
- ✅ Subsequent requests include session cookie
- ✅ `/api/me` returns 200 OK with user data
- ✅ No 403 Forbidden errors

### Django Admin Should:
- ✅ Load with proper styling
- ✅ No 404 errors for CSS/JS files

## If Still Not Working

If after all these steps you still get 403 errors:

1. **Check PythonAnywhere error logs** for specific error messages
2. **Verify all files were uploaded** correctly
3. **Verify .env file was saved** correctly
4. **Verify web application was reloaded**
5. **Try a complete restart** of the web application in PythonAnywhere dashboard

## Contact Support

If issues persist after following this guide:
1. Provide the output of `debug_session.py`
2. Provide the output of `cat .env`
3. Provide PythonAnywhere error logs
4. Provide browser console errors
