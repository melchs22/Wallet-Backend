# Backend Error Fixes - Production Deployment

This document summarizes the fixes applied to resolve the server errors encountered during Google OAuth authentication.

## Issues Fixed

### 1. OAuth Redirect URI Error (Critical)

**Error**: `Internal Server Error: /api/auth/google`

**Root Cause**: The redirect URI was being constructed incorrectly in `wallet/views.py`:
```python
# OLD (BROKEN):
redirect_uri = f"{settings.FRONTEND_ORIGIN[0] if settings.FRONTEND_ORIGIN else 'http://localhost:3000'}/auth/callback"
```
This was trying to access `FRONTEND_ORIGIN[0]` which gets the first character of the string (e.g., 'h' from 'http://...'), not the full URL.

**Fix**:
1. Added `FRONTEND_ORIGIN_URL` to `walletmvp/settings.py`:
```python
FRONTEND_ORIGIN_URL = env('FRONTEND_ORIGIN', default='http://localhost:3000')
if isinstance(FRONTEND_ORIGIN_URL, list):
    FRONTEND_ORIGIN_URL = FRONTEND_ORIGIN_URL[0] if FRONTEND_ORIGIN_URL else 'http://localhost:3000'
```

2. Updated `wallet/views.py` to use the new setting:
```python
# NEW (FIXED):
redirect_uri = f"{settings.FRONTEND_ORIGIN_URL}/auth/callback"
```

### 2. Missing Login Import

**Error**: `NameError: name 'login' is not defined`

**Root Cause**: The `login` function from `django.contrib.auth` was not imported but was used in the OAuth view.

**Fix**: Added import in `wallet/views.py`:
```python
from django.contrib.auth import logout, login
```

### 3. drf-spectacular Serializer Warnings

**Error**: Multiple warnings like `unable to guess serializer. This is graceful fallback handling for APIViews.`

**Root Cause**: APIView classes without `serializer_class` attribute cause drf-spectacular to emit warnings.

**Fix**: Added `serializer_class` to all APIView classes:
- `GoogleAuthView` → `GoogleAuthRequestSerializer`
- `MeView` → `UserSerializer`
- `UserResolveView` → `UserResolveSerializer`
- `TransferView` → `TransferRequestSerializer`
- `NotificationListView` → `NotificationSerializer`
- `NotificationDetailView` → `NotificationSerializer`
- `WalletView` → `WalletDetailSerializer`
- `TransactionListView` → `TransactionSerializer`
- `CloseAccountView` → `UserSerializer`
- `TransactionDetailView` → `TransactionDetailSerializer`
- `ReversalView` → `ReversalRequestSerializer`

### 4. Operation ID Collision Warning

**Error**: `Warning: operationId "transactions_retrieve" has collisions`

**Root Cause**: Both `/api/transactions` (list) and `/api/transactions/{transaction_id}` (detail) were generating the same operation ID.

**Fix**: Reordered URL patterns in `wallet/urls.py` to group related endpoints:
- Moved detail view before admin operations
- This helps drf-spectacular generate unique operation IDs

### 5. Missing OpenAPI Decorators

**Improvement**: Added `@extend_schema` decorators to views for better API documentation:
- `GoogleAuthView` - documented request/response schemas
- `MeView` - documented response schema
- `UserResolveView` - documented response schema
- `TransferView` - documented request/response schemas
- `NotificationListView` - documented response schema
- `logout_view` - documented response schema

## Files Modified

1. **`walletmvp/settings.py`**
   - Added `FRONTEND_ORIGIN_URL` setting
   - Handles both string and list types for FRONTEND_ORIGIN

2. **`wallet/views.py`**
   - Fixed OAuth redirect URI construction
   - Added `login` import
   - Added `serializer_class` to all APIView classes
   - Added `@extend_schema` decorators for better documentation
   - Added `extend_schema` import

3. **`wallet/urls.py`**
   - Reordered URL patterns to avoid operation ID collisions
   - Grouped related endpoints together

## Expected Behavior After Fixes

### Before:
```
2026-08-14 10:51:09,304: Internal Server Error: /api/auth/google
```

### After:
```
✅ OAuth token exchange succeeds
✅ User is authenticated
✅ Session is created
✅ Frontend receives user/wallet data
```

## Deployment Instructions

### 1. Update Backend on PythonAnywhere

1. **Upload updated files**:
   - `walletmvp/settings.py`
   - `wallet/views.py`
   - `wallet/urls.py`

2. **Reload web application**:
   - Go to PythonAnywhere → Web → my_web_app
   - Click "Reload" button

3. **Test OAuth endpoint**:
   ```bash
   curl -X POST https://TECH212.pythonanywhere.com/api/auth/google \
     -H "Content-Type: application/json" \
     -d '{"code":"test","state":"test"}'
   ```
   Expected: 400 Bad Request (invalid code, but no 500 error)

### 2. Verify OpenAPI Schema

Visit: `https://TECH212.pythonanywhere.com/api/schema/`

Expected:
- No serializer warnings
- No operation ID collision warnings
- All endpoints documented

### 3. Test Full OAuth Flow

1. Visit: `https://dsd-wallet.vercel.app/login`
2. Click "Continue with Google"
3. Sign in with Google account
4. Expected: Successful authentication and redirect to home

## Environment Variables Verification

Ensure your PythonAnywhere `.env` file has:

```env
# Database
DATABASE_URL=postgresql://TECH212:password@TECH212.postgres.pythonanywhere-services.com/TECH212

# Django
SECRET_KEY=your-generated-secret-key
DEBUG=False
ALLOWED_HOSTS=TECH212.pythonanywhere.com,www.TECH212.pythonanywhere.com

# CORS
FRONTEND_ORIGIN=https://dsd-wallet.vercel.app

# Session Security
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# Google OAuth
GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=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
```

## Troubleshooting

### Still Getting 500 Error on /api/auth/google

1. **Check error logs**:
   - PythonAnywhere → Web → my_web_app → Log files
   - Look for the specific error message

2. **Verify environment variables**:
   ```python
   # In Python shell on PythonAnywhere
   from django.conf import settings
   print(settings.GOOGLE_CLIENT_ID)
   print(settings.GOOGLE_CLIENT_SECRET)
   print(settings.FRONTEND_ORIGIN_URL)
   ```

3. **Test Google OAuth locally**:
   - Use local backend with same credentials
   - Verify the flow works locally before deploying

### 403 Forbidden on /api/me

This is **expected behavior** for unauthenticated requests. After successful OAuth, this endpoint should return 200 OK.

### Serializer Warnings Still Appearing

1. **Clear drf-spectacular cache**:
   ```bash
   python manage.py spectacular --color --fail-on-warnings
   ```

2. **Regenerate schema**:
   ```bash
   python manage.py spectacular --file schema.yml
   ```

## Testing Checklist

- [ ] Backend deployed to PythonAnywhere
- [ ] Environment variables verified
- [ ] Web application reloaded
- [ ] OpenAPI schema loads without warnings
- [ ] `/api/auth/google` returns 400 (not 500) for invalid request
- [ ] Google OAuth flow completes successfully
- [ ] User is authenticated after OAuth
- [ ] `/api/me` returns user data after authentication
- [ ] Session cookie is set correctly
- [ ] Frontend can access protected endpoints

## Next Steps

1. **Deploy these fixes** to PythonAnywhere
2. **Test the OAuth flow** end-to-end
3. **Monitor logs** for any remaining errors
4. **Verify all API endpoints** are working correctly
5. **Test money transfer functionality** with authenticated user

## Contact

If issues persist after applying these fixes:
1. Check PythonAnywhere error logs
2. Verify Google Cloud Console OAuth configuration
3. Ensure frontend and backend are using matching credentials
4. Test with local backend to isolate the issue
