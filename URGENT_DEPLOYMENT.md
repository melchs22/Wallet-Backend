# Critical Production Deployment Instructions

## URGENT: Users Can Login But Get 403 Errors

The logs show that users are successfully logging in with Google OAuth, but then getting 403 Forbidden errors on subsequent API requests. This means the session is being created but not being recognized.

## Root Cause Analysis

### Issues Identified:

1. **Session not being saved properly** - The `login()` function is called but session might not be persisting
2. **Static files not collected** - 404 errors for `/static/admin/css/*` files
3. **Default permission classes** - Global `IsAuthenticated` requirement might interfere with session auth

### Why This Matters:

The fixes I made to your local files (`walletmvp/settings.py`, `wallet/views.py`, etc.) have NOT been deployed to PythonAnywhere yet. The production server is still running the old code with the bugs.

## Immediate Actions Required

### 1. Deploy Updated Files to PythonAnywhere

You MUST upload these files to PythonAnywhere:

**Critical Files:**
- `walletmvp/settings.py` - Session configuration, authentication classes, static files
- `wallet/views.py` - OAuth redirect URI fix, session save enforcement
- `wallet/urls.py` - URL pattern reordering
- `collect_static.sh` - New script for collecting static files

### 2. Update PythonAnywhere Environment Variables

Add/update these in your PythonAnywhere `.env` file:

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

### 3. Configure Static Files in PythonAnywhere

In PythonAnywhere Dashboard → Web → my_web_app → Static files:

**Add this mapping:**
- **URL**: `/static/`
- **Directory**: `/home/TECH212/mysite/staticfiles/`

### 4. Collect Static Files on PythonAnywhere

Run this in PythonAnywhere bash console:

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

### 5. Reload Web Application

In PythonAnywhere Dashboard → Web → my_web_app:
- Click the "Reload" button

## Key Fixes Deployed

### 1. OAuth Redirect URI Fix

**Before (Broken):**
```python
redirect_uri = f"{settings.FRONTEND_ORIGIN[0] if settings.FRONTEND_ORIGIN else 'http://localhost:3000'}/auth/callback"
```
This was getting the first character (e.g., 'h') instead of the full URL.

**After (Fixed):**
```python
redirect_uri = f"{settings.FRONTEND_ORIGIN_URL}/auth/callback"
```

### 2. Session Save Enforcement

**Added to OAuth view:**
```python
response = Response(response_data, status=status.HTTP_200_OK)
request.session.save()  # Force session to be saved
return response
```

### 3. Session Configuration

**Updated settings:**
```python
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 2592000  # 30 days
SESSION_COOKIE_SAMESITE = None  # For cross-origin
SESSION_SAVE_EVERY_REQUEST = True
SESSION_REFRESH_AT_REQUEST = True
```

### 4. Authentication Classes

**Updated REST Framework:**
```python
'DEFAULT_AUTHENTICATION_CLASSES': [
    'rest_framework.authentication.SessionAuthentication',
    'rest_framework.authentication.BasicAuthentication',
],
# Removed DEFAULT_PERMISSION_CLASSES to allow per-view control
```

### 5. Static Files Configuration

**Updated settings:**
```python
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
```

## Why Users Are Getting 403 After Login

### The Flow:

1. ✅ User clicks "Continue with Google"
2. ✅ Google OAuth completes
3. ✅ Backend creates session with `login(request, user)`
4. ❌ Session cookie not being sent to frontend (CORS issue)
5. ❌ Frontend doesn't have session cookie
6. ❌ Subsequent requests get 403 (no credentials)

### The Fixes Address:

1. **SESSION_COOKIE_SAMESITE=None** - Allows cross-origin cookies
2. **CORS_ALLOW_CREDENTIALS=True** - Allows cookies to be sent cross-origin
3. **CSRF_TRUSTED_ORIGINS** - Allows CSRF validation cross-origin
4. **request.session.save()** - Forces session to be saved
5. **Frontend URL in CORS** - Explicitly whitelisted

## Testing After Deployment

### 1. Test OAuth Flow

1. Visit `https://dsd-wallet.vercel.app/login`
2. Click "Continue with Google"
3. Sign in with Google account
4. **Check browser developer tools:**
   - Application → Cookies → Look for `sessionid` cookie
   - Network tab → Check `/api/auth/google` returns 200 OK
   - Network tab → Check subsequent requests include `sessionid` cookie

### 2. Test Authenticated Endpoints

After login, try:
- `GET /api/me` - Should return 200 OK with user data
- `GET /api/wallet` - Should return 200 OK with wallet data
- `GET /api/notifications` - Should return 200 OK with notifications

### 3. Test Django Admin

1. Visit `https://TECH212.pythonanywhere.com/admin/`
2. Should load with proper styling (no 404 errors for CSS/JS)
3. Login with superuser credentials
4. Should see the admin dashboard

## If Still Getting 403 After Deployment

### Debug Steps:

1. **Check session cookie is being set:**
```python
# In PythonAnywhere bash console
python manage.py shell
from django.contrib.sessions.models import Session
sessions = Session.objects.all()
print(f"Active sessions: {sessions.count()}")
```

2. **Check session data:**
```python
from django.contrib.sessions.models import Session
for session in Session.objects.all()[:5]:
    print(f"Session: {session.session_key}")
    print(f"Expires: {session.expire_date}")
    print(f"Data: {session.get_decoded()}")
```

3. **Check CORS configuration:**
```python
from django.conf import settings
print(f"CORS_ALLOWED_ORIGINS: {settings.CORS_ALLOWED_ORIGINS}")
print(f"CORS_ALLOW_CREDENTIALS: {settings.CORS_ALLOW_CREDENTIALS}")
```

4. **Check session configuration:**
```python
from django.conf import settings
print(f"SESSION_COOKIE_SAMESITE: {settings.SESSION_COOKIE_SAMESITE}")
print(f"SESSION_COOKIE_SECURE: {settings.SESSION_COOKIE_SECURE}")
print(f"SESSION_COOKIE_AGE: {settings.SESSION_COOKIE_AGE}")
```

5. **Check authentication classes:**
```python
from django.conf import settings
print(f"DEFAULT_AUTHENTICATION_CLASSES: {settings.REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']}")
```

## Static Files 404 Errors

The 404 errors for `/static/admin/css/*` indicate static files haven't been collected or mapped.

### Fix:

1. Run `collectstatic` on PythonAnywhere
2. Configure static files mapping in PythonAnywhere dashboard
3. Reload web application

## Summary of Files to Deploy

### From `/Users/tutumelchizedek/Downloads/Wallet App/`:

1. `walletmvp/settings.py` - Session, auth, static files config
2. `wallet/views.py` - OAuth fix, session save
3. `wallet/urls.py` - URL pattern fixes
4. `collect_static.sh` - New script
5. `static/` - New directory (empty but needed)

### Environment Variables to Update:

PythonAnywhere `.env` file with all the session/CSRF settings shown above.

## Deployment Priority

**Do this in order:**

1. Upload updated files to PythonAnywhere
2. Update `.env` file with new environment variables
3. Run `collectstatic` to collect static files
4. Configure static files mapping in PythonAnywhere dashboard
5. Reload web application
6. Test OAuth flow
7. Test authenticated endpoints
8. Test Django admin

## Contact Support

If after deploying these fixes you still have issues:

1. Check PythonAnywhere error logs
2. Verify all environment variables are set correctly
3. Check that static files were collected successfully
4. Test with local backend to isolate the issue
5. Check browser console for CORS errors
6. Verify Google OAuth configuration

The local backend has all the fixes applied. The production backend (PythonAnywhere) needs these same fixes deployed.
