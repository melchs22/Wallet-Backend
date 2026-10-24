import base64
import hashlib
import os
import secrets

import pyotp
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.utils import timezone

from wallet.models import AdminTOTP


SETUP_MAX_AGE = 10 * 60
LOGIN_MAX_AGE = 5 * 60


def _key():
    return hashlib.sha256(settings.SECRET_KEY.encode()).digest()


def _encrypt(value):
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, value.encode(), None)
    return 'aesgcm:v1:' + base64.urlsafe_b64encode(nonce + ciphertext).decode()


def _decrypt(value):
    payload = base64.urlsafe_b64decode(value[len('aesgcm:v1:'):])
    return AESGCM(_key()).decrypt(payload[:12], payload[12:], None).decode()


def issue_setup_token(user, record):
    nonce = secrets.token_urlsafe(24)
    record.setup_token_hash = make_password(nonce)
    record.save(update_fields=['setup_token_hash', 'updated_at'])
    return signing.dumps({'user_id': user.pk, 'nonce': nonce}, salt='admin-totp-setup')


def load_setup_token(token):
    try:
        payload = signing.loads(token, salt='admin-totp-setup', max_age=SETUP_MAX_AGE)
        record = AdminTOTP.objects.select_related('user').get(user_id=payload['user_id'], is_enabled=False)
        if not check_password(payload['nonce'], record.setup_token_hash):
            return None, None
        return record.user, record
    except ( signing.BadSignature, AdminTOTP.DoesNotExist, KeyError, TypeError):
        return None, None


def provision_secret(record):
    if not record.secret_encrypted:
        record.secret_encrypted = _encrypt(pyotp.random_base32())
        record.save(update_fields=['secret_encrypted', 'updated_at'])
    return _decrypt(record.secret_encrypted)


def verify_code(record, code):
    if not record.secret_encrypted or not code:
        return False
    try:
        return pyotp.TOTP(_decrypt(record.secret_encrypted)).verify(str(code), valid_window=1)
    except (ValueError, TypeError):
        return False


def provisioning_uri(user, secret):
    return pyotp.TOTP(secret).provisioning_uri(
        name=user.email,
        issuer_name=getattr(settings, 'ADMIN_TOTP_ISSUER', 'Wallet Admin'),
    )


def confirm(record):
    record.is_enabled = True
    record.confirmed_at = timezone.now()
    record.setup_token_hash = ''
    record.save(update_fields=['is_enabled', 'confirmed_at', 'setup_token_hash', 'updated_at'])


def issue_login_token(user):
    return signing.dumps({'user_id': user.pk}, salt='admin-totp-login')


def load_login_user(token):
    try:
        from wallet.models import User
        payload = signing.loads(token, salt='admin-totp-login', max_age=LOGIN_MAX_AGE)
        return User.objects.get(pk=payload['user_id'], is_staff=True, status='active')
    except (signing.BadSignature, User.DoesNotExist, KeyError, TypeError, ValueError):
        return None
