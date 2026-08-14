# Google OAuth Setup Guide for DSD Wallet Frontend

This guide explains how to configure Google OAuth for the live frontend at `https://dsd-wallet.vercel.app`.

## Current Configuration

Your frontend already has the OAuth callback implemented at:
- **Callback URL**: `https://dsd-wallet.vercel.app/auth/callback`
- **Login Page**: `https://dsd-wallet.vercel.app/login`

## Step 1: Create or Update Google Cloud Project

### If you already have a project:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your existing project
3. Proceed to Step 2

### If you need to create a new project:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Enter project name: `DSD Wallet Production`
4. Click "Create"
5. Wait for project creation (may take a few seconds)

## Step 2: Configure OAuth Consent Screen

1. In Google Cloud Console, go to **APIs & Services** → **OAuth consent screen**
2. Select **External** user type (for production)
3. Click "Create"

### Fill in OAuth Consent Screen Details:

**App information:**
- **App name**: `DSD Wallet`
- **User support email**: Your support email
- **App logo**: Upload your app logo (optional but recommended)
- **Application home page**: `https://dsd-wallet.vercel.app`
- **Authorized domains**: `vercel.app`
- **Developer contact**: Your email
- **Privacy policy URL**: `https://dsd-wallet.vercel.app/privacy` (or your privacy policy page)
- **Terms of service URL**: `https://dsd-wallet.vercel.app/terms` (or your terms page)

4. Click "Save and Continue"

**Scopes:**
- You don't need to add scopes manually - they will be configured when you create the OAuth client
- Click "Save and Continue"

**Test users:**
- Add yourself as a test user (optional but recommended for testing)
- Click "Save and Continue"

**Summary:**
- Review your settings
- Click "Back to Dashboard"

## Step 3: Create OAuth 2.0 Credentials

1. In Google Cloud Console, go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. Application type: **Web application**
4. Name: `DSD Wallet Production`

### Configure Authorized Redirect URIs:

Add the following redirect URIs:

**Required for Production:**
```
https://dsd-wallet.vercel.app/auth/callback
```

**Recommended for Local Development:**
```
http://localhost:3000/auth/callback
```

**Optional for Backend Testing:**
```
https://TECH212.pythonanywhere.com/auth/callback
```

5. Click **Create**

### Save Your Credentials

1. After creation, you'll see a popup with:
   - **Client ID**: Copy this - you'll need it for your frontend
   - **Client Secret**: Copy this - you'll need it for your backend

2. **Important**: Store these securely and never commit them to version control

## Step 4: Enable Required APIs

1. In Google Cloud Console, go to **APIs & Services** → **Library**
2. Search for and enable:
   - **Google+ API** (if available, otherwise skip)
   - **Google Identity** or **Google OAuth2 API**
3. These APIs are typically enabled automatically when you create OAuth credentials

## Step 5: Configure Frontend Environment Variables

### In Vercel Dashboard:

1. Go to your Vercel project dashboard
2. Go to **Settings** → **Environment Variables**
3. Add the following variables:

```env
NEXT_PUBLIC_API_BASE_URL=https://TECH212.pythonanywhere.com/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
```

**Example:**
```env
NEXT_PUBLIC_API_BASE_URL=https://tutumelchizedek.pythonanywhere.com/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=123456789-abcdefghijklmnop.apps.googleusercontent.com
```

4. Click **Save**
5. **Important**: Trigger a new deployment after updating environment variables

### In Local Development:

Update your local `.env.local` file:
```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api
NEXT_PUBLIC_GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
```

## Step 6: Configure Backend Environment Variables

### In PythonAnywhere:

Update your `.env` file with the production credentials:

```env
GOOGLE_CLIENT_ID=256666248694-iocf5uppdg0n9sq5i2krtp96bp80nio7.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=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
FRONTEND_ORIGIN=https://dsd-wallet.vercel.app
```

**Complete Example:**
```env
DATABASE_URL=postgresql://username:password@username.postgres.pythonanywhere-services.com/username
SECRET_KEY=your-generated-secret-key
DEBUG=False
ALLOWED_HOSTS=your-username.pythonanywhere.com,www.your-username.pythonanywhere.com
FRONTEND_ORIGIN=https://dsd-wallet.vercel.app
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
GOOGLE_CLIENT_ID=123456789-abcdefghijklmnop.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-abcdefghijklmnop
```

## Step 7: Configure CORS in Backend

### Update Django Settings

In `walletmvp/settings.py`, ensure CORS is configured:

```python
CORS_ALLOWED_ORIGINS = [
    "https://dsd-wallet.vercel.app",
    "http://localhost:3000",  # For local development
]

CORS_ALLOW_CREDENTIALS = True
```

### Allowed Hosts

```python
ALLOWED_HOSTS = [
    'your-username.pythonanywhere.com',
    'www.your-username.pythonanywhere.com',
]
```

## Step 8: Test the OAuth Flow

### Production Test:

1. Visit `https://dsd-wallet.vercel.app/login`
2. Click "Continue with Google"
3. You should be redirected to Google's OAuth consent screen
4. Sign in with your Google account
5. You should be redirected back to `https://dsd-wallet.vercel.app/auth/callback`
6. If successful, you should be redirected to `/home` (or `/onboarding/handle` for new users)

### Local Development Test:

1. Ensure your backend is running locally: `python manage.py runserver`
2. Set local environment variables
3. Visit `http://localhost:3000/login`
4. Test the flow as above

## Step 9: Troubleshooting OAuth Issues

### "redirect_uri_mismatch" Error

**Cause**: The redirect URI in Google Console doesn't match what your app is sending.

**Solution**:
1. Check what redirect URI your app is using (look at browser URL bar when OAuth starts)
2. Add that exact URI to Google Console
3. Make sure to include the trailing slash: `/auth/callback` not `/auth/callback/`

### "access_denied" Error

**Cause**: User denied consent or OAuth consent screen not configured.

**Solution**:
1. Ensure OAuth consent screen is configured
2. Try signing out of other Google accounts
3. Use incognito/private browsing to test

### "invalid_client" Error

**Cause**: Wrong Client ID or Client Secret.

**Solution**:
1. Verify Client ID matches what's in Google Console
2. Check for extra spaces in environment variables
3. Regenerate Client Secret if necessary

### "unauthorized_client" Error

**Cause**: OAuth client not authorized for the project.

**Solution**:
1. Verify you're using the correct Google Cloud project
2. Check OAuth client ID matches your project
3. Ensure the project is not in a suspended state

### 401 Errors After Login

**Cause**: Backend session issue or CORS configuration.

**Solution**:
1. Check that backend is running and accessible
2. Verify CORS configuration
3. Check that `FRONTEND_ORIGIN` matches your frontend URL exactly
4. Check backend logs for specific error messages

## Step 10: Security Best Practices

### Never Expose Secrets

- Never commit `.env` files or actual API keys to version control
- Use environment variables for all sensitive data
- Regularly rotate Client Secret if compromised

### Use HTTPS Only

- OAuth only works with HTTPS in production
- PythonAnywhere provides SSL automatically
- Vercel provides SSL automatically

### Domain Verification

- In Google Cloud Console, you may need to verify your domain
- Add a DNS TXT record if prompted
- This is required for some OAuth features

### Monitor OAuth Usage

- Check Google Cloud Console for OAuth usage metrics
- Monitor for unusual patterns (could indicate abuse)
- Set up alerts for API quota limits

## Step 11: Production Checklist

- [ ] Google Cloud project created or selected
- [ ] OAuth consent screen configured
- [ ] OAuth 2.0 credentials created (Web application)
- [ ] Redirect URI added: `https://dsd-wallet.vercel.app/auth/callback`
- [ ] Client ID and Client Secret saved securely
- [ ] Frontend environment variables updated in Vercel
- [ ] Backend environment variables updated in PythonAnywhere
- [ ] CORS configured for frontend domain
- [ ] Backend redeployed (if changes made)
- [ ] Frontend redeployed (if environment variables changed)
- [ ] OAuth flow tested successfully
- [ ] Local development still works with different redirect URI

## Step 12: Monitor OAuth Performance

### Check Google Cloud Console

1. Go to **APIs & Services** → **Credentials**
2. Click on your OAuth 2.0 client ID
3. View usage statistics and error rates

### Backend Monitoring

Monitor for:
- Successful authentications vs failures
- OAuth error rates
- User registration rates
- Session creation rates

### Frontend Monitoring

Monitor for:
- Login conversion rate
- OAuth callback success rate
- Time from login start to session establishment

## OAuth Flow Diagram

```
User clicks "Continue with Google"
         ↓
Frontend generates state, stores in sessionStorage
         ↓
Redirect to Google OAuth: https://accounts.google.com/o/oauth2/v2/auth
         ↓
User signs in and grants consent
         ↓
Google redirects to: https://dsd-wallet.vercel.app/auth/callback?code=...&state=...
         ↓
Frontend verifies state matches
         ↓
Frontend POSTs to backend: POST /api/auth/google
         ↓
Backend exchanges code for tokens with Google
         ↓
Backend creates session, returns user/wallet data
         ↓
Frontend stores user in TanStack Query cache
         ↓
Frontend redirects to /home or /onboarding/handle
```

## Additional Resources

- [Google OAuth 2.0 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Google Cloud Console](https://console.cloud.google.com/)
- [Vercel Environment Variables](https://vercel.com/docs/projects/environment-variables)
- [Django OAuth2 Package](https://django-oauth-toolkit.readthedocs.io/)

## Support

If you encounter OAuth issues:

1. Check Google Cloud Console error logs
2. Verify redirect URIs match exactly
3. Test with incognito mode to rule out caching issues
4. Check browser console for specific error messages
5. Verify backend is running and accessible
6. Check CORS configuration matches frontend domain

## Next Steps

Once OAuth is working:

1. Test the complete user onboarding flow
2. Test session persistence across page refreshes
3. Test logout and re-login
4. Monitor the first few days for any OAuth-related issues
5. Consider setting up analytics to track authentication metrics
