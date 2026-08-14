# Session Enforcement and Static Files Configuration

This document explains the session enforcement settings to keep users logged in and the static files configuration for Django admin.

## Session Enforcement Configuration

### Goal
Keep users logged in for extended periods without requiring frequent re-authentication.

### Configuration Applied

Updated `walletmvp/settings.py` with the following session settings:

```python
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
SESSION_COOKIE_SAMESITE = env('SESSION_COOKIE_SAMESITE', default='Lax')
SESSION_COOKIE_DOMAIN = None
SESSION_COOKIE_AGE = 2592000  # 30 days (30 * 24 * 60 * 60)
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_REFRESH_AT_REQUEST = True
```

### Settings Explained

| Setting | Value | Purpose |
|---------|-------|---------|
| `SESSION_ENGINE` | `django.contrib.sessions.backends.db` | Store sessions in database (more reliable than file-based) |
| `SESSION_COOKIE_HTTPONLY` | `True` | Prevent JavaScript access to session cookie (security) |
| `SESSION_COOKIE_SECURE` | `True` (production) / `False` (dev) | Only send cookie over HTTPS |
| `SESSION_COOKIE_SAMESITE` | `None` (production) / `Lax` (dev) | Cross-origin cookie policy |
| `SESSION_COOKIE_DOMAIN` | `None` | Let browser determine the correct domain |
| `SESSION_COOKIE_AGE` | `2592000` (30 days) | Session cookie lifetime in seconds |
| `SESSION_SAVE_EVERY_REQUEST` | `True` | Update session on every request |
| `SESSION_EXPIRE_AT_BROWSER_CLOSE` | `False` | Session persists even if browser is closed |
| `SESSION_REFRESH_AT_REQUEST` | `True` | Refresh session expiration on each activity |

### Session Lifetime Calculation

- **30 days** = 30 × 24 × 60 × 60 = 2,592,000 seconds
- This means users stay logged in for 30 days of inactivity
- With `SESSION_REFRESH_AT_REQUEST=True`, the 30-day timer resets on every API call
- **Effective**: Users stay logged in indefinitely as long as they use the app at least once every 30 days

### Session Refresh Behavior

When `SESSION_REFRESH_AT_REQUEST=True`:
1. User logs in at Day 0
2. User uses the app on Day 15 → Session expires at Day 45 (reset)
3. User uses the app on Day 40 → Session expires at Day 70 (reset)
4. User stops using the app → Session expires 30 days after last activity

This provides a good balance between security and user convenience.

## Static Files Configuration

### Goal
Collect and serve static files (CSS, JavaScript, images) correctly for Django admin and the API.

### Configuration Applied

Updated `walletmvp/settings.py` with static files settings:

```python
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
```

### Settings Explained

| Setting | Value | Purpose |
|---------|-------|---------|
| `STATIC_URL` | `/static/` | URL prefix for static files in production |
| `STATIC_ROOT` | `BASE_DIR / 'staticfiles'` | Directory where collected static files are stored |
| `STATICFILES_DIRS` | `[BASE_DIR / 'static']` | Directory containing app-specific static files |

### Static Files Flow

1. **Development**:
   - Django serves static files from each app's `static/` directory
   - No collection needed
   - Files are served from `STATICFILES_DIRS`

2. **Production**:
   - All static files are collected into `STATIC_ROOT`
   - Web server (PythonAnywhere) serves files from `STATIC_ROOT`
   - Collection done via `python manage.py collectstatic`

### Collecting Static Files

#### Manual Collection

```bash
cd /path/to/project
source venv/bin/activate
python manage.py collectstatic --noinput --clear
```

#### Using the Provided Script

A shell script `collect_static.sh` is provided for convenience:

```bash
cd /path/to/project
./collect_static.sh
```

The script:
- Activates the virtual environment if it exists
- Runs `collectstatic` with `--noinput` (no prompts) and `--clear` (clean previous collection)

### PythonAnywhere Static Files Configuration

1. **In PythonAnywhere Dashboard**:
   - Go to Web → my_web_app
   - Scroll to "Static files" section
   - Add configuration:
     - **URL**: `/static/`
     - **Directory**: `/home/TECH212/mysite/staticfiles/`

2. **Why this matters**:
   - Django admin needs static files for CSS/JS
   - Without this, admin UI will look broken (no styling)
   - The `/static/` URL maps to the `staticfiles/` directory

### Creating Static Directory

A `static/` directory has been created in the project root for any custom static files you might need:

```bash
mkdir -p static
```

This directory is included in `STATICFILES_DIRS` so any files placed here will be collected during `collectstatic`.

## Django Admin UI

### Accessing Django Admin

1. **Create a superuser** (if not already created):
```bash
python manage.py createsuperuser
```

2. **Access admin panel**:
   - URL: `https://TECH212.pythonanywhere.com/admin/`
   - Login with superuser credentials

3. **Admin Panel Features**:
   - View and manage users
   - View and manage wallets
   - View and manage transactions
   - View and manage ledger entries
   - View and manage notifications
   - Admin-only transaction reversal

### Why Static Files Matter for Admin

Django admin relies heavily on static files:
- **CSS**: Admin styling, layout, responsive design
- **JavaScript**: Dynamic behavior, form validation, inline editing
- **Images**: Django logo, icons, graphics

Without proper static files configuration:
- Admin panel will load but look completely broken
- No styling, forms won't work properly
- JavaScript features will fail

### Verifying Static Files

After collecting static files, verify:

```bash
# Check that staticfiles directory exists
ls -la staticfiles/

# Should contain:
# - admin/ (Django admin files)
# - rest_framework/ (DRF files)
# - drf_spectacular/ (API docs files)
# - Any custom static files
```

## Environment Variables

### Session Settings in `.env`

**Local Development:**
```env
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
SESSION_COOKIE_SAMESITE=Lax
CSRF_COOKIE_SAMESITE=Lax
SESSION_COOKIE_AGE=2592000  # 30 days
```

**Production (PythonAnywhere):**
```env
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SESSION_COOKIE_SAMESITE=None
CSRF_COOKIE_SAMESITE=None
CSRF_TRUSTED_ORIGINS=https://dsd-wallet.vercel.app
SESSION_COOKIE_AGE=2592000  # 30 days
```

## Deployment Checklist

### Session Enforcement

- [ ] `SESSION_COOKIE_AGE` set to 2592000 (30 days)
- [ ] `SESSION_EXPIRE_AT_BROWSER_CLOSE` set to False
- [ ] `SESSION_REFRESH_AT_REQUEST` set to True
- [ ] `SESSION_SAVE_EVERY_REQUEST` set to True
- [ ] Environment variables updated on PythonAnywhere
- [ ] Tested that users stay logged in across browser sessions
- [ ] Tested that session refreshes on activity

### Static Files

- [ ] `STATIC_URL` set to `/static/`
- [ ] `STATIC_ROOT` set to `BASE_DIR / 'staticfiles'`
- [ ] `STATICFILES_DIRS` configured
- [ ] `static/` directory created
- [ ] `collect_static.sh` script created and made executable
- [ ] Run `python manage.py collectstatic` locally to test
- [ ] PythonAnywhere static files mapping configured
- [ ] Static files collected on PythonAnywhere
- [ ] Django admin UI loads correctly with styling
- [ ] Admin CSS/JS files are accessible

## Troubleshooting

### Users Getting Logged Out

**Check 1: Session cookie age**
```python
# In Python shell
from django.conf import settings
print(settings.SESSION_COOKIE_AGE)  # Should be 2592000
```

**Check 2: Session expiration**
```python
# Check session database
from django.contrib.sessions.models import Session
sessions = Session.objects.all()
for session in sessions:
    print(f"Expires: {session.expire_date}")
```

**Check 3: Cookie being set**
- Open browser developer tools
- Check Application → Cookies
- Look for `sessionid` cookie
- Check expiration date

### Static Files Not Loading

**Check 1: Static files collected**
```bash
ls -la staticfiles/
```
Should contain admin, rest_framework, etc.

**Check 2: PythonAnywhere mapping**
- URL: `/static/`
- Directory: `/home/TECH212/mysite/staticfiles/`

**Check 3: STATIC_URL in settings**
```python
# Should be '/static/' (with leading slash)
print(settings.STATIC_URL)
```

**Check 4: Admin URL**
```python
# Should include admin in INSTALLED_APPS
' django.contrib.admin' in settings.INSTALLED_APPS
```

### Admin UI Looks Broken

**Symptoms**: No styling, forms don't work correctly

**Solution**:
1. Collect static files: `python manage.py collectstatic`
2. Verify PythonAnywhere static files mapping
3. Check browser console for 404 errors on static files
4. Verify `STATIC_URL` is correct

## Security Considerations

### Session Security

**30-day session is acceptable if:**
- HTTPS is enforced (`SESSION_COOKIE_SECURE=True`)
- Cookies are httpOnly (`SESSION_COOKIE_HTTPONLY=True`)
- CSRF protection is enabled
- Session engine is database-based (not file-based)
- Session is refreshed on activity

**Risk Mitigation:**
- Users can manually logout if device is compromised
- Session can be revoked by admin
- Monitor for unusual activity
- Consider implementing device fingerprinting

### Static Files Security

**Best Practices:**
- Never serve sensitive data via static files
- Use HTTPS for all static file requests
- Set appropriate cache headers
- Regularly update Django to get security patches
- Scan static files for vulnerabilities

## Performance Considerations

### Session Storage

**Database sessions** (current configuration):
- Pros: Reliable, scalable, can query sessions
- Cons: Database overhead on every request
- Alternative: Redis (better for high traffic)

**Recommendation**:
- Current setup is fine for MVP
- Consider Redis if you have >1000 concurrent users

### Static Files

**Current setup**:
- PythonAnywhere serves static files from disk
- Good for MVP
- Can be optimized with CDN for high traffic

**Recommendation**:
- Current setup is fine for MVP
- Consider CDN (CloudFlare, AWS CloudFront) for production scale

## Testing

### Session Persistence Test

1. Login to the app
2. Close browser
3. Reopen browser
4. Visit the app
5. **Expected**: Still logged in (no need to re-authenticate)

### Session Refresh Test

1. Login to the app
2. Note the session expiration (check cookie)
3. Use the app (make an API call)
4. Check session expiration again
5. **Expected**: Expiration time has been refreshed

### Static Files Test

1. Visit `https://TECH212.pythonanywhere.com/admin/`
2. **Expected**: Admin UI loads with proper styling
3. Check browser network tab
4. **Expected**: No 404 errors for CSS/JS files

## Next Steps

1. **Deploy session configuration** to PythonAnywhere
2. **Deploy static files configuration** to PythonAnywhere
3. **Run collectstatic** on PythonAnywhere
4. **Configure static files mapping** in PythonAnywhere dashboard
5. **Test session persistence** across browser sessions
6. **Test Django admin UI** loads correctly
7. **Monitor session logs** for any issues
8. **Consider implementing session revocation** for security events

## Files Modified

1. **`walletmvp/settings.py`**
   - Updated session configuration (30-day lifetime)
   - Added session refresh on activity
   - Updated static files configuration
   - Added `STATIC_ROOT` and `STATICFILES_DIRS`

2. **`.env` and `.env.example`**
   - Added `SESSION_COOKIE_AGE` setting
   - Updated session/CSRF settings documentation

3. **`collect_static.sh`** (new file)
   - Script to collect static files
   - Made executable

4. **`static/` directory** (new directory)
   - Created for custom static files
   - Included in `STATICFILES_DIRS`

5. **`PYTHONANYWHERE_DEPLOYMENT.md`**
   - Updated static files section
   - Added collectstatic script usage
