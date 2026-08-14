# Authentication and Session Configuration Fixes

This document explains the authentication/session configuration fixes to resolve 403 errors after login and ensure proper session handling.

## Understanding the Errors

### Expected vs Unexpected Errors

**EXPECTED (Normal Behavior):**
- `403 Forbidden` on `/api/me` - User is not logged in yet
- `403 Forbidden` on `/api/transfers` - User is not logged in yet
- These endpoints require authentication, so 403 is correct for unauthenticated requests

**UNEXPECTED (Need Fixing):**
- `500 Internal Server Error` on `/api/auth/google` - Prevents login from working
- `403 Forbidden` AFTER successful login - Session not being properly set/recognized

## Fixes Applied

### 1. REST Framework Authentication Configuration

**Problem**: Missing explicit authentication classes in REST_FRAMEWORK settings, which could cause session authentication to not work properly.

**Fix**: Added explicit authentication classes to `walletmvp/settings.py`:
```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    # ... other settings
}
```

**Why This Matters**:
- `SessionAuthentication` ensures Django sessions are used for API authentication
- `BasicAuthentication` provides fallback for testing (can be removed in production)
- Explicitly setting these prevents Django REST Framework from using default settings that might not work with your session configuration

### 2. Session Cookie Configuration

**Problem**: Session cookies might not be set correctly for cross-origin requests from Vercel to PythonAnywhere.

**Fix**: Enhanced session configuration in `walletmvp/settings.py`:
```python
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
SESSION_COOKIE_SAMESITE = env('SESSION_COOKIE_SAMESITE', default='Lax')
SESSION_COOKIE_DOMAIN = None  # Let browser determine domain
SESSION_COOKIE_AGE = 86400  # 1 day
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
```

**Key Changes**:
- `SESSION_ENGINE = 'django.contrib.sessions.backends.db'` - Stores sessions in database (more reliable than file-based)
- `SESSION_COOKIE_SAMESITE` - Made configurable (None for production, Lax for local)
- `SESSION_SAVE_EVERY_REQUEST = True` - Ensures session is updated on every request
- `SESSION_COOKIE_DOMAIN = None` - Allows browser to determine the correct domain

### 3. CSRF Configuration

**Problem**: CSRF protection might block legitimate API requests from the frontend.

**Fix**: Enhanced CSRF configuration in `walletmvp/settings.py`:
```python
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
CSRF_COOKIE_SAMESITE = env('CSRF_COOKIE_SAMESITE', default='Lax')
CSRF_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=['https://dsd-wallet.vercel.app'])
```

**Key Changes**:
- `CSRF_TRUSTED_ORIGINS` - Explicitly whitelist the frontend domain
- `CSRF_COOKIE_SAMESITE` - Made configurable (None for production, Lax for local)
- This allows CSRF tokens to work correctly with cross-origin requests

### 4. Environment Variables

**Updated `.env.example` and `.env`** to include session/CSRF settings:

**Local Development:**
```env
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SAMESITE=Lax
```

**Production (PythonAnywhere):**
```env
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SESSION_COOKIE_SAMESITE=None
CSRF_COOKIE_SAMESITE=None
CSRF_TRUSTED_ORIGINS=https://dsd-wallet.vercel.app
```

**Why `None` for SameSite in Production:**
- `None` allows cross-origin cookie sharing with proper validation
- Required when frontend and backend are on different domains (Vercel vs PythonAnywhere)
- `Lax` only works for same-site requests, which would break the authentication flow

## How Session Authentication Works

### Normal Flow (After Fixes):

1. **User clicks "Continue with Google"**
   - Frontend redirects to Google OAuth
   - State parameter is generated and stored in sessionStorage

2. **User authenticates with Google**
   - Google redirects to `/auth/callback`
   - Frontend sends POST to `/api/auth/google` with authorization code

3. **Backend processes OAuth**
   - Exchanges code for tokens
   - Verifies ID token
   - Creates or retrieves user
   - **Calls `login(request, user)`** - This creates the session
   - Returns user/wallet data

4. **Session cookie is set**
   - Django sets `sessionid` cookie in response
   - Cookie is sent back to frontend (if CORS is configured correctly)
   - Browser stores the cookie

5. **Subsequent API requests**
   - Frontend includes `sessionid` cookie automatically
   - Django REST Framework authenticates using `SessionAuthentication`
   - Request is allowed (200 OK)

### What Was Wrong Before:

- Session might not be saved properly
- Cookie might not be sent to frontend (CORS issue)
- Cookie might be rejected by browser (SameSite=Lax with cross-origin)
- CSRF token might not be validated correctly

## Deployment Instructions

### 1. Update PythonAnywhere Environment Variables

In your PythonAnywhere `.env` file, add/update:

```env
# Database
DATABASE_URL=postgresql://TECH212:password@TECH212.postgres.pythonanywhere-services.com/TECH212

# Django
SECRET_KEY=your-generated-secret-key
DEBUG=False
ALLOWED_HOSTS=TECH212.pythonanywhere.com,www.TECH212.pythonanywhere.com

# CORS
FRONTEND_ORIGIN=https://dsd-wallet.vercel.app

# Session Security (PRODUCTION)
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SESSION_COOKIE_SAMESITE=None
CSRF_COOKIE_SAMESITE=None
CSRF_TRUSTED_ORIGINS=https://dsd-wallet.vercel.app

# Google OAuth
GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=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
```

### 2. Upload Updated Files to PythonAnywhere

Update these files:
- `walletmvp/settings.py`
- `wallet/views.py` (from previous fixes)
- `wallet/urls.py` (from previous fixes)

### 3. Run Database Migrations (if needed)

```bash
cd ~/mysite
source venv/bin/activate
python manage.py migrate
```

### 4. Reload Web Application

In PythonAnywhere:
- Go to Web → my_web_app
- Click "Reload"

### 5. Test the Authentication Flow

1. Visit `https://dsd-wallet.vercel.app/login`
2. Click "Continue with Google"
3. Sign in with Google account
4. Check browser developer tools:
   - **Application tab → Cookies** - Look for `sessionid` cookie
   - **Network tab** - Check that `/api/auth/google` returns 200 OK
   - **Network tab** - Check that subsequent requests include the `sessionid` cookie

## Troubleshooting

### Still Getting 403 After Login

**Check 1: Is session cookie being set?**
- Open browser developer tools
- Go to Application → Cookies
- Look for `sessionid` cookie
- If missing, session is not being created

**Check 2: Is CORS configured correctly?**
- Check that `CORS_ALLOW_CREDENTIALS = True` in settings
- Check that `FRONTEND_ORIGIN` matches your frontend URL exactly
- Check that browser is not blocking cross-origin cookies

**Check 3: Is SameSite setting correct?**
- For cross-origin (different domains), use `SESSION_COOKIE_SAMESITE=None`
- For same-origin (same domain), use `SESSION_COOKIE_SAMESITE=Lax`

**Check 4: Is CSRF token being sent?**
- Check that `X-CSRFToken` header is included in POST requests
- Check that CSRF cookie is being set
- Check that `CSRF_TRUSTED_ORIGINS` includes your frontend domain

### Session Not Persisting

**Check 1: Session engine**
- Ensure `SESSION_ENGINE = 'django.contrib.sessions.backends.db'`
- Check that database sessions table exists

**Check 2: Session age**
- Check `SESSION_COOKIE_AGE` setting
- Check `SESSION_EXPIRE_AT_BROWSER_CLOSE` setting

**Check 3: Cookie security**
- Check `SESSION_COOKIE_SECURE` setting (must match HTTPS)
- Check `SESSION_COOKIE_HTTPONLY` setting

### 403 on All Requests (Even After Login)

**Check 1: Authentication classes**
- Ensure `SessionAuthentication` is in `DEFAULT_AUTHENTICATION_CLASSES`
- Ensure session middleware is in `MIDDLEWARE`

**Check 2: User is actually logged in**
- Check that `login(request, user)` is being called in OAuth view
- Check that user status is `ACTIVE` (not suspended)

**Check 3: Permission classes**
- Ensure endpoints have correct permission classes
- Some endpoints might have custom permission requirements

## Testing Checklist

- [ ] Environment variables updated on PythonAnywhere
- [ ] Session configuration updated in settings.py
- [ ] CSRF configuration updated in settings.py
- [ ] REST Framework authentication configured
- [ ] Files uploaded to PythonAnywhere
- [ ] Web application reloaded
- [ ] Database migrations run
- [ ] OAuth flow tested end-to-end
- [ ] Session cookie is set after login
- [ ] Subsequent requests include session cookie
- [ ] `/api/me` returns 200 OK after login
- [ ] `/api/transfers` returns 200 OK after login
- [ ] Handle can be saved after login
- [ ] User can logout and login again

## Security Notes

### Important Security Considerations

1. **Never disable CSRF protection** in production
2. **Always use HTTPS** in production with `SESSION_COOKIE_SECURE=True`
3. **Use httpOnly cookies** to prevent XSS attacks
4. **Set appropriate SameSite** policy based on your deployment:
   - Same domain: `Lax`
   - Cross domain: `None` (with proper validation)
5. **Regularly rotate session keys** and SECRET_KEY
6. **Monitor session logs** for unusual activity

### Development vs Production

**Development (localhost):**
- `SESSION_COOKIE_SECURE=False` (HTTP allowed)
- `CSRF_COOKIE_SECURE=False` (HTTP allowed)
- `SESSION_COOKIE_SAMESITE=Lax` (same origin)

**Production (PythonAnywhere + Vercel):**
- `SESSION_COOKIE_SECURE=True` (HTTPS only)
- `CSRF_COOKIE_SECURE=True` (HTTPS only)
- `SESSION_COOKIE_SAMESITE=None` (cross-origin allowed)
- `CSRF_TRUSTED_ORIGINS=https://dsd-wallet.vercel.app`

## Next Steps

1. **Deploy these fixes** to PythonAnywhere
2. **Test the authentication flow** thoroughly
3. **Monitor session logs** for any issues
4. **Test cookie behavior** in different browsers
5. **Verify CSRF protection** is working correctly
6. **Test logout and re-login** functionality

## Support

If authentication issues persist after applying these fixes:
1. Check PythonAnywhere error logs
2. Verify all environment variables are set correctly
3. Test with local backend to isolate the issue
4. Check browser console for CORS errors
5. Verify Google OAuth configuration in Google Cloud Console
