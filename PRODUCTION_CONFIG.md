# DSD Wallet Production Configuration Summary

This document summarizes the production configuration for the DSD Wallet frontend and backend deployment.

## Production URLs

- **Frontend**: https://dsd-wallet.vercel.app
- **Backend**: https://TECH212.pythonanywhere.com
- **API Endpoint**: https://TECH212.pythonanywhere.com/api

## Google OAuth Credentials

### Client ID
```
256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
```

### Client Secret
```
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
```

### OAuth Callback URLs
- Frontend: https://dsd-wallet.vercel.app/auth/callback
- Backend (testing): https://TECH212.pythonanywhere.com/auth/callback

## Frontend Configuration (Vercel)

### Environment Variables

In Vercel Dashboard → Settings → Environment Variables:

```env
NEXT_PUBLIC_API_BASE_URL=https://TECH212.pythonanywhere.com/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
```

### Local Development (.env.local)

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
```

## Backend Configuration (PythonAnywhere)

### Environment Variables (.env)

```env
# Database (PostgreSQL)
DATABASE_URL=postgresql://TECH212:password@TECH212.postgres.pythonanywhere-services.com/TECH212

# Django Configuration
SECRET_KEY=your-generated-secret-key
DEBUG=False
ALLOWED_HOSTS=TECH212.pythonanywhere.com,www.TECH212.pythonanywhere.com

# CORS Configuration
FRONTEND_ORIGIN=https://dsd-wallet.vercel.app

# Session Security
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# Google OAuth
GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=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
```

### Django Settings (walletmvp/settings.py)

```python
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', 'TECH212.pythonanywhere.com', 'www.TECH212.pythonanywhere.com'])

CORS_ALLOWED_ORIGINS = env.list('FRONTEND_ORIGIN', default=['http://localhost:3000', 'https://dsd-wallet.vercel.app'])
CORS_ALLOW_CREDENTIALS = True

SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=True)
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=True)
```

## Deployment Checklist

### Frontend (Vercel)

- [x] Environment variables configured
- [x] NEXT_PUBLIC_API_BASE_URL set to production backend
- [x] NEXT_PUBLIC_GOOGLE_CLIENT_ID set
- [ ] Trigger deployment after environment variable changes
- [ ] Test OAuth flow
- [ ] Test API connectivity

### Backend (PythonAnywhere)

- [x] Environment variables configured
- [x] ALLOWED_HOSTS includes TECH212.pythonanywhere.com
- [x] CORS allows https://dsd-wallet.vercel.app
- [x] Google OAuth credentials configured
- [x] Session security settings enabled
- [ ] PostgreSQL database created
- [ ] Database migrations run
- [ ] WSGI configuration updated
- [ ] Static files collected
- [ ] Web application reloaded
- [ ] Test API endpoints
- [ ] Test OAuth callback

### Google Cloud Console

- [x] OAuth 2.0 client created
- [x] Redirect URI added: https://dsd-wallet.vercel.app/auth/callback
- [x] Redirect URI added: https://TECH212.pythonanywhere.com/auth/callback
- [ ] OAuth consent screen configured for production
- [ ] Test OAuth flow end-to-end

## Testing Steps

### 1. Test Backend API

```bash
# Test unauthenticated endpoint
curl https://TECH212.pythonanywhere.com/api/me
# Expected: 401 Unauthorized

# Test OpenAPI schema
curl https://TECH212.pythonanywhere.com/api/schema/
# Expected: 200 OK with OpenAPI JSON
```

### 2. Test Frontend

1. Visit https://dsd-wallet.vercel.app/login
2. Click "Continue with Google"
3. Sign in with Google account
4. Verify redirect to https://dsd-wallet.vercel.app/auth/callback
5. Verify redirect to home or onboarding page
6. Test money transfer functionality

### 3. Test OAuth Flow

1. Open browser developer tools
2. Navigate to https://dsd-wallet.vercel.app/login
3. Click "Continue with Google"
4. Check that state parameter is generated
5. Verify state is stored in sessionStorage
6. After callback, verify state matches
7. Check that session cookie is set
8. Verify user data is cached in TanStack Query

## Security Notes

### Important Security Reminders

1. **Never commit `.env` files** to version control
2. **Use strong passwords** for PostgreSQL
3. **Generate a unique SECRET_KEY** for production
4. **Keep Google Client Secret private** - never expose in frontend
5. **Always use HTTPS** in production
6. **Enable SSL certificate** on PythonAnywhere (automatic)
7. **Monitor logs** for suspicious activity
8. **Regularly rotate secrets** if compromised

### CSRF Protection

- Django CSRF protection is enabled
- CSRF token sent as X-CSRFToken header on non-GET requests
- CSRFTOKEN cookie is read and validated
- Frontend reads CSRFTOKEN from cookies

### Session Security

- httpOnly session cookies (not accessible via JavaScript)
- Secure flag set to True in production
- SameSite set to 'Lax'
- Session age: 1 day (configurable)

## Monitoring

### Backend Monitoring

1. **PythonAnywhere Logs**:
   - Error logs: Web → my_web_app → Log files
   - Access logs: Same location
   - Check for 4xx and 5xx errors

2. **Database Monitoring**:
   - Disk usage in Databases section
   - Connection count
   - Slow queries

3. **Balance Reconciliation**:
   - Schedule daily job: python manage.py reconcile_balances
   - Check for ledger drift
   - Alert on discrepancies

### Frontend Monitoring

1. **Vercel Analytics**:
   - Page views
   - Error rates
   - Performance metrics

2. **Browser Console**:
   - Network errors
   - OAuth failures
   - API errors

## Troubleshooting

### Common Issues

#### 401 Unauthorized

- Check session cookie is set
- Verify backend is running
- Check CORS configuration
- Verify CSRF token is sent

#### 403 Forbidden

- Check CORS_ALLOWED_ORIGINS
- Verify frontend domain is allowed
- Check CSRF token configuration

#### OAuth Redirect URI Mismatch

- Verify redirect URI in Google Cloud Console
- Check for trailing slashes
- Ensure exact match with frontend URL

#### Database Connection Error

- Verify DATABASE_URL is correct
- Check PostgreSQL server is running
- Ensure database user has permissions

## Support Documentation

- **PythonAnywhere Deployment**: PYTHONANYWHERE_DEPLOYMENT.md
- **Google OAuth Setup**: GOOGLE_OAUTH_SETUP.md
- **Backend README**: README.md
- **Frontend README**: dsd-wallet/README.md

## Next Steps

1. **Deploy Backend**:
   - Follow PYTHONANYWHERE_DEPLOYMENT.md
   - Upload project to PythonAnywhere
   - Configure environment variables
   - Run migrations
   - Test API endpoints

2. **Deploy Frontend**:
   - Update Vercel environment variables
   - Trigger deployment
   - Test OAuth flow
   - Test API connectivity

3. **Production Monitoring**:
   - Set up log aggregation
   - Configure error tracking (Sentry)
   - Set up alerts for critical errors
   - Monitor balance reconciliation

4. **Post-Deployment**:
   - Test complete user flow
   - Monitor first few days
   - Gather user feedback
   - Plan for scaling

## Contact

For issues or questions:
- Backend: PythonAnywhere dashboard
- Frontend: Vercel dashboard
- OAuth: Google Cloud Console
