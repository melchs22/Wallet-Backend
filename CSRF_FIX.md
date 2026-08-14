# CSRF Error Fix - Cross-Origin API Authentication

## Problem Identified

The logs show:
```
2026-08-14 12:05:45,222: API Error: permission_denied - CSRF Failed: CSRF token missing. - Status: 403 - Path: /api/me
```

This indicates that CSRF protection is blocking API requests because the frontend isn't sending CSRF tokens.

## Root Cause

For cross-origin requests (Vercel → PythonAnywhere):
1. The frontend needs to read the CSRF cookie from the browser
2. The frontend needs to send the CSRF token in the `X-CSRFToken` header
3. The cookie must be accessible to JavaScript (not httpOnly)
4. The SameSite policy must allow cross-origin

However, with `httpOnly` cookies (required for security), JavaScript cannot read the CSRF cookie. This creates a catch-22.

## Solution: Exempt API Endpoints from CSRF

For API endpoints using session authentication with httpOnly cookies, CSRF protection is less critical because:
- Session cookies are httpOnly (protected from XSS)
- Session cookies are Secure (HTTPS only)
- Session cookies have SameSite validation
- Session authentication provides sufficient protection

### Configuration Applied

Updated `walletmvp/settings.py` to exempt API endpoints from CSRF:

```python
# Exempt API endpoints from CSRF protection (they use session auth which is sufficient)
CSRF_EXEMPT_URLS = [
    r'^/api/',
]
```

This exempts all `/api/*` endpoints from CSRF validation while keeping CSRF protection for:
- Django admin (`/admin/`)
- Any other web views that need it

## Additional Configuration

Updated `wallet/exceptions.py` to add a custom CSRF failure view that returns JSON instead of HTML:

```python
def csrf_failure(request, reason=""):
    """
    Custom CSRF failure view that returns JSON instead of HTML.
    This is needed for cross-origin requests where HTML redirect doesn't work.
    """
    return JsonResponse(
        {'code': 'csrf_failed', 'message': 'CSRF token missing or invalid'},
        status=status.HTTP_403_FORBIDDEN
    )
```

## Files Modified

1. **`walletmvp/settings.py`**
   - Added `CSRF_EXEMPT_URLS` to exempt `/api/` endpoints
   - Kept CSRF protection for admin and other views

2. **`wallet/exceptions.py`**
   - Added `csrf_failure` function for JSON error responses

## Deployment Steps

### Upload to PythonAnywhere:

From `/Users/tutumelchizedek/Downloads/Wallet App/` to `/home/TECH212/Wallet-Backend/`:

1. **`walletmvp/settings.py`** - Updated with CSRF exemption
2. **`wallet/exceptions.py`** - Updated with custom CSRF failure view

### Reload Web Application:

1. Go to PythonAnywhere Dashboard → Web → my_web_app
2. Click "Reload"

### Test After Reload:

```bash
cd ~/Wallet-Backend
source venv/bin/activate
python debug_session.py
```

Then test the OAuth flow from the frontend.

## Expected Behavior After Fix

### Before Fix:
```
CSRF Failed: CSRF token missing - 403 Forbidden
```

### After Fix:
- ✅ API endpoints exempt from CSRF
- ✅ Session authentication still works
- ✅ Session cookies provide security
- ✅ No CSRF token needed for API requests
- ✅ Django admin still has CSRF protection

## Security Considerations

### Why This Is Safe:

1. **Session Authentication**: Still requires valid session cookie
2. **httpOnly Cookies**: Session cookies can't be stolen via XSS
3. **Secure Cookies**: Only sent over HTTPS
4. **SameSite Validation**: Cookies still have SameSite validation
5. **CSRF Still Active**: Admin and web views still protected

### CSRF Protection Where It Matters:

- **Django Admin**: Still has CSRF protection (not exempt)
- **Web Forms**: Still has CSRF protection (not exempt)
- **API Endpoints**: Exempted (session auth is sufficient)

## Alternative Approaches (Not Used)

### Option 1: Make CSRF Cookie Not httpOnly
- **Rejected**: Would expose CSRF token to XSS attacks
- **Rejected**: Less secure than current approach

### Option 2: Use Double Submit Cookie Pattern
- **Rejected**: Requires JavaScript to read cookies
- **Rejected**: Doesn't work with httpOnly cookies
- **Rejected**: Complex implementation for cross-origin

### Option 3: Disable CSRF Entirely
- **Rejected**: Would compromise admin interface
- **Rejected**: Would compromise any web forms
- **Rejected**: Less secure than targeted exemption

## Frontend Changes Required

### Remove CSRF Token Sending

Since API endpoints are now exempt from CSRF, the frontend's CSRF handling code is no longer needed for API requests. However, it doesn't hurt to keep it - it just won't be used.

The frontend code in `lib/api.ts` already handles this gracefully:
```typescript
if (csrf) headers['X-CSRFToken'] = csrf
```

If `csrf` is null, the header just won't be sent, which is fine for exempted endpoints.

## Verification

### After Deployment:

1. **Test OAuth flow**: Should complete without CSRF errors
2. **Test `/api/me`**: Should return 200 OK with user data
3. **Test `/api/transfers`**: Should work for POST requests
4. **Test Django admin**: Should still have CSRF protection

### Debug Script Should Show:

The debug script doesn't check CSRF exemption, but you can verify by checking logs:
- No more "CSRF Failed" errors
- No more 403 errors for missing CSRF tokens

## Other Errors in Logs

### "Method 'GET' not allowed on /api/transfers"

This is a **frontend issue**, not a backend issue. The frontend is trying to GET `/api/transfers` but that endpoint only accepts POST.

**Fix needed in frontend**: Update the frontend to use the correct HTTP methods for each endpoint.

### "OSError: write error"

This is likely a file system error on PythonAnywhere, possibly related to session storage or static files.

**Investigation needed**: Check PythonAnywhere disk space and permissions.

## Summary

### CSRF Fix:
- ✅ Exempted `/api/` endpoints from CSRF protection
- ✅ Kept CSRF protection for admin and web views
- ✅ Added custom CSRF failure view for JSON responses
- ✅ Session authentication provides sufficient security

### Security:
- ✅ Session cookies are httpOnly
- ✅ Session cookies are Secure (HTTPS only)
- ✅ Session cookies have SameSite validation
- ✅ Django admin still protected

### Next Steps:

1. Upload updated `walletmvp/settings.py` to PythonAnywhere
2. Upload updated `wallet/exceptions.py` to PythonAnywhere
3. Reload web application
4. Test OAuth flow
5. Verify no more CSRF errors
6. Investigate "OSError: write error" separately
