#!/usr/bin/env python
"""
Debug script to verify session configuration is working correctly.
Run this on PythonAnywhere after deployment to diagnose authentication issues.
"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'walletmvp.settings')
django.setup()

from django.conf import settings
from django.contrib.sessions.models import Session
from django.contrib.auth import get_user_model

User = get_user_model()

print("=" * 60)
print("SESSION CONFIGURATION DEBUG")
print("=" * 60)

print("\n1. Session Settings:")
print(f"   SESSION_ENGINE: {settings.SESSION_ENGINE}")
print(f"   SESSION_COOKIE_HTTPONLY: {settings.SESSION_COOKIE_HTTPONLY}")
print(f"   SESSION_COOKIE_SECURE: {settings.SESSION_COOKIE_SECURE}")
print(f"   SESSION_COOKIE_SAMESITE: {settings.SESSION_COOKIE_SAMESITE}")
print(f"   SESSION_COOKIE_DOMAIN: {settings.SESSION_COOKIE_DOMAIN}")
print(f"   SESSION_COOKIE_AGE: {settings.SESSION_COOKIE_AGE} seconds ({settings.SESSION_COOKIE_AGE / 86400:.1f} days)")
print(f"   SESSION_SAVE_EVERY_REQUEST: {settings.SESSION_SAVE_EVERY_REQUEST}")
print(f"   SESSION_EXPIRE_AT_BROWSER_CLOSE: {settings.SESSION_EXPIRE_AT_BROWSER_CLOSE}")
print(f"   SESSION_REFRESH_AT_REQUEST: {settings.SESSION_REFRESH_AT_REQUEST}")

print("\n2. CSRF Settings:")
print(f"   CSRF_COOKIE_SECURE: {settings.CSRF_COOKIE_SECURE}")
print(f"   CSRF_COOKIE_SAMESITE: {settings.CSRF_COOKIE_SAMESITE}")
print(f"   CSRF_COOKIE_HTTPONLY: {settings.CSRF_COOKIE_HTTPONLY}")
print(f"   CSRF_TRUSTED_ORIGINS: {settings.CSRF_TRUSTED_ORIGINS}")

print("\n3. CORS Settings:")
print(f"   CORS_ALLOWED_ORIGINS: {settings.CORS_ALLOWED_ORIGINS}")
print(f"   CORS_ALLOW_CREDENTIALS: {settings.CORS_ALLOW_CREDENTIALS}")

print("\n4. REST Framework Authentication:")
print(f"   DEFAULT_AUTHENTICATION_CLASSES: {settings.REST_FRAMEWORK.get('DEFAULT_AUTHENTICATION_CLASSES', [])}")
print(f"   DEFAULT_PERMISSION_CLASSES: {settings.REST_FRAMEWORK.get('DEFAULT_PERMISSION_CLASSES', [])}")

print("\n5. Frontend Origin:")
print(f"   FRONTEND_ORIGIN: {getattr(settings, 'FRONTEND_ORIGIN', 'NOT SET')}")
print(f"   FRONTEND_ORIGIN_URL: {getattr(settings, 'FRONTEND_ORIGIN_URL', 'NOT SET')}")

print("\n6. Static Files:")
print(f"   STATIC_URL: {settings.STATIC_URL}")
print(f"   STATIC_ROOT: {settings.STATIC_ROOT}")
print(f"   STATICFILES_DIRS: {settings.STATICFILES_DIRS}")

print("\n7. Session Database:")
try:
    session_count = Session.objects.count()
    print(f"   Active sessions in database: {session_count}")
    
    if session_count > 0:
        print("\n   Recent sessions:")
        for session in Session.objects.all()[:5]:
            print(f"     - Key: {session.session_key[:20]}...")
            print(f"       Expires: {session.expire_date}")
            print(f"       Data keys: {list(session.get_decoded().keys())}")
except Exception as e:
    print(f"   Error checking sessions: {e}")

print("\n8. User Count:")
try:
    user_count = User.objects.count()
    print(f"   Total users: {user_count}")
    print(f"   Active users: {User.objects.filter(status='active').count()}")
except Exception as e:
    print(f"   Error checking users: {e}")

print("\n" + "=" * 60)
print("RECOMMENDATIONS:")
print("=" * 60)

# Check for common issues
issues = []

if settings.SESSION_COOKIE_SAMESITE == 'Lax' and 'https://dsd-wallet.vercel.app' in str(settings.CSRF_TRUSTED_ORIGINS):
    issues.append("⚠️  SESSION_COOKIE_SAMESITE is 'Lax' but you're using cross-origin. Set to 'None' for production.")

if not settings.CORS_ALLOW_CREDENTIALS:
    issues.append("⚠️  CORS_ALLOW_CREDENTIALS is False. Set to True for session cookies to work cross-origin.")

if 'https://dsd-wallet.vercel.app' not in str(settings.CORS_ALLOWED_ORIGINS):
    issues.append("⚠️  Frontend domain not in CORS_ALLOWED_ORIGINS. Add it.")

if 'https://dsd-wallet.vercel.app' not in str(settings.CSRF_TRUSTED_ORIGINS):
    issues.append("⚠️  Frontend domain not in CSRF_TRUSTED_ORIGINS. Add it.")

if 'rest_framework.authentication.SessionAuthentication' not in settings.REST_FRAMEWORK.get('DEFAULT_AUTHENTICATION_CLASSES', []):
    issues.append("⚠️  SessionAuthentication not in DEFAULT_AUTHENTICATION_CLASSES. Add it.")

if not settings.SESSION_SAVE_EVERY_REQUEST:
    issues.append("⚠️  SESSION_SAVE_EVERY_REQUEST is False. Set to True for better session persistence.")

if settings.SESSION_COOKIE_AGE < 86400:
    issues.append("⚠️  SESSION_COOKIE_AGE is less than 1 day. Consider increasing to 2592000 (30 days).")

if issues:
    print("\nIssues found:")
    for issue in issues:
        print(f"  {issue}")
else:
    print("\n✅ All settings look correct!")

print("\n" + "=" * 60)
