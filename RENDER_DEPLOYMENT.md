# Render Deployment Guide for Wallet MVP Backend

This guide covers deploying the Wallet MVP Django backend to Render.

## Deployment Information

- **Backend URL**: https://wallet-backend-lqhq.onrender.com
- **Frontend URL**: https://dsd-wallet.vercel.app
- **Database**: SQLite (for now, can migrate to PostgreSQL later)
- **Deployment Platform**: Render

## Configuration Summary

All settings are hardcoded in `walletmvp/settings.py`:

### Django Settings
- `SECRET_KEY`: Hardcoded in settings.py
- `DEBUG`: False (production mode)
- `ALLOWED_HOSTS`: wallet-backend-lqhq.onrender.com, www.wallet-backend-lqhq.onrender.com

### Database
- SQLite (db.sqlite3)
- Stored in project root
- Easy to migrate to PostgreSQL later

### CORS
- `FRONTEND_ORIGIN`: https://dsd-wallet.vercel.app
- `CORS_ALLOW_CREDENTIALS`: True

### Session
- `SESSION_COOKIE_SECURE`: True
- `CSRF_COOKIE_SECURE`: True
- `SESSION_COOKIE_SAMESITE`: None (for cross-origin)
- `SESSION_COOKIE_AGE`: 2592000 (30 days)

### CSRF
- `CSRF_TRUSTED_ORIGINS`: https://dsd-wallet.vercel.app
- `CSRF_EXEMPT_URLS`: [r'^/api/'] (API endpoints exempt)

### Google OAuth
- `GOOGLE_CLIENT_ID`: Hardcoded in settings.py
- `GOOGLE_CLIENT_SECRET`: Hardcoded in settings.py

## Frontend Configuration

### Environment Variables

Update Vercel environment variables:

```env
NEXT_PUBLIC_API_BASE_URL=https://wallet-backend-lqhq.onrender.com/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=256666248694-ioc5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
```

### Google Cloud Console

Update the authorized redirect URI:
- Add: `https://dsd-wallet.vercel.app/auth/callback`
- Add: `https://wallet-backend-lqhq.onrender.com/auth/callback` (for testing)

## Deployment Steps

### 1. Update Backend Settings

The `walletmvp/settings.py` file has been updated with all hardcoded settings.

### 2. Update Frontend Environment Variables

In Vercel Dashboard → Settings → Environment Variables:
- `NEXT_PUBLIC_API_BASE_URL`: `https://wallet-backend-lqhq.onrender.com/api`
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID`: `256666248694-iocf5uppdg0n9peaktp96bp80nio7.apps.googleusercontent.com`

### 3. Deploy to Render

1. Push code to GitHub repository
2. Connect Render to GitHub repository
3. Render will auto-deploy on push
4. Or manually trigger deployment in Render dashboard

### 4. Update Google Cloud Console

1. Go to Google Cloud Console
2. Edit OAuth 2.0 client ID
3. Add authorized redirect URIs:
   - `https://dsd-wallet.vercel.app/auth/callback`
   - `https://wallet-backend-lqhq.onrender.com/auth/callback`

### 5. Test Deployment

#### Backend Tests:
```bash
# Test API is accessible
curl https://wallet-backend-lqhq.onrender.com/api/me
# Expected: 401 Unauthorized (authenticated only)

# Test OpenAPI schema
curl https://wallet-backend-lqhq.onrender.com/api/schema/
# Expected: 200 OK with OpenAPI JSON
```

#### Frontend Tests:
1. Visit https://dsd-wallet.vercel.app/login
2. Click "Continue with Google"
3. Complete OAuth flow
4. Verify session is created
5. Test authenticated endpoints

## Static Files

### Configuration (in settings.py)
```python
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
```

### Collect Static Files
```bash
python manage.py collectstatic --noinput --clear
```

### Render Static Files Configuration

Render requires static files to be served from `staticfiles/` directory. This is automatic with the configuration above.

## Database

### Current Setup
- SQLite database (db.sqlite3)
- Stored in project root
- Simple, no external dependencies

### Migration to PostgreSQL (Future)

To migrate to PostgreSQL later:

1. Create PostgreSQL database on Render
2. Update DATABASES in settings.py:
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'wallet',
        'USER': 'wallet_user',
        'PASSWORD': 'your-password',
        'HOST': 'your-database-host',
        'PORT': '5432',
    }
}
```
3. Deploy to Render
4. Run migrations

## Security Notes

### Current Setup
- SQLite database (no external dependencies)
- Hardcoded credentials (simpler deployment)
- Session-based authentication
- CSRF protection exempted for API endpoints
- Session cookies are httpOnly and Secure

### Recommendations
- Generate a unique SECRET_KEY for production
- Use environment variables for sensitive data in production
- Migrate to PostgreSQL for production use
- Regular database backups

## Troubleshooting

### 403 Forbidden Errors

If users get 403 after login:
1. Check CORS configuration in settings.py
2. Check session cookie settings
3. Verify frontend URL is whitelisted
4. Check CSRF exemption is active

### 502 Bad Gateway

- Check Render dashboard for deployment status
- Check error logs in Render
- Verify web service is running

### 500 Internal Server Error

- Check Render error logs
- Check database connectivity
- Verify all settings are correct

## Files Modified

### Backend
1. **`walletmvp/settings.py`** - All settings hardcoded for Render
2. **`.env`** - Updated with Render backend URL
3. **`.env.example`** - Updated with Render backend URL

### Frontend
1. **`.env`** - Updated API base URL to Render
2. **`.env.example`** - Updated API base URL to Render
3. **`README.md`** - Updated backend URL reference

## Verification Checklist

- [ ] Backend settings updated with Render URL
- [ ] Database configured as SQLite
- - [ ] ALLOWED_HOSTS includes Render domain
- [ ] CORS configured for frontend
- [ ] Session configuration for cross-origin
- - CSRF exemption for API endpoints
- [ ] Google OAuth credentials hardcoded
- [ ] Frontend environment variables updated
- [ ] Google Cloud Console redirect URIs updated
- [ ] Backend deployed to Render
- [ ] Frontend deployed to Vercel
- [ ] OAuth flow tested end-to-end
- [ ] Session persistence tested
- [ ] API endpoints tested

## Next Steps

1. Deploy backend to Render
2. Update frontend environment variables on Vercel
3. Update Google Cloud Console redirect URIs
4. Test complete user flow
5. Monitor Render logs for issues
- Consider migrating to PostgreSQL
- Consider using environment variables for secrets

## Support

For issues specific to Render:
- Check Render dashboard logs
- Check Render documentation
- Verify deployment configuration

For general application issues:
- Check this documentation
- Check previous troubleshooting guides
- Check error logs
