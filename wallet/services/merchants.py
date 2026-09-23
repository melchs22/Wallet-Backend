import secrets
import re
import base64
import hashlib
import os

from django.contrib.auth.hashers import make_password
from django.conf import settings
from django.db import transaction
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from wallet.models import Merchant, MerchantApiKey, MerchantMode, MerchantStatus, User, Wallet, WalletStatus


def merchant_public_identifier(merchant):
    """Return a stable, non-secret identifier suitable for QR/public links."""
    if merchant.public_identifier:
        return merchant.public_identifier
    base = re.sub(r'[^a-z0-9]+', '-', merchant.business_name.lower()).strip('-') or 'merchant'
    candidate = base
    suffix = 2
    while Merchant.objects.filter(public_identifier=candidate).exclude(pk=merchant.pk).exists():
        candidate = f'{base}-{suffix}'
        suffix += 1
    merchant.public_identifier = candidate[:80]
    merchant.save(update_fields=['public_identifier', 'updated_at'])
    return candidate


def merchant_code(merchant):
    """Return a random, stable six-digit code for manual and QR payments."""
    if merchant.merchant_code:
        return merchant.merchant_code
    while True:
        candidate = f'{secrets.randbelow(1_000_000):06d}'
        if not Merchant.objects.filter(merchant_code=candidate).exists():
            merchant.merchant_code = candidate
            merchant.save(update_fields=['merchant_code', 'updated_at'])
            return candidate


def _key_prefix(mode):
    return 'live' if mode == MerchantMode.LIVE else 'test'


def _legacy_secret_cipher():
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def _secret_key():
    return hashlib.sha256(settings.SECRET_KEY.encode()).digest()


def _encrypt_secret(value):
    nonce = os.urandom(12)
    encrypted = AESGCM(_secret_key()).encrypt(nonce, value.encode(), None)
    return 'aesgcm:v1:' + base64.urlsafe_b64encode(nonce + encrypted).decode()


def decrypt_merchant_secret(api_key):
    if not api_key.secret_key_encrypted:
        return None
    stored = api_key.secret_key_encrypted
    if stored.startswith('aesgcm:v1:'):
        payload = base64.urlsafe_b64decode(stored[len('aesgcm:v1:'):])
        return AESGCM(_secret_key()).decrypt(payload[:12], payload[12:], None).decode()
    # Existing keys were encrypted with Fernet; retain read compatibility so
    # rotating the application does not invalidate issued merchant secrets.
    try:
        return _legacy_secret_cipher().decrypt(stored.encode()).decode()
    except InvalidToken:
        raise ValueError('Stored merchant secret could not be decrypted') from None


def generate_merchant_api_keys(merchant, mode):
    """
    Create or rotate an API key pair for a merchant/mode.
    Returns raw (public_key, secret_key) shown exactly once.
    """
    prefix = _key_prefix(mode)
    public_key = f'pk_{prefix}_{secrets.token_urlsafe(24)}'
    secret_key = f'sk_{prefix}_{secrets.token_urlsafe(32)}'
    secret_key_prefix = secret_key[:20]

    with transaction.atomic():
        if MerchantApiKey.objects.filter(merchant=merchant, mode=mode, is_active=True).exists():
            raise ValueError('Credentials have already been issued for this environment.')
        MerchantApiKey.objects.update_or_create(
            merchant=merchant,
            mode=mode,
            defaults={
                'public_key': public_key,
                'secret_key_prefix': secret_key_prefix,
                'secret_key_hash': make_password(secret_key),
                'secret_key_encrypted': _encrypt_secret(secret_key),
                'is_active': True,
            },
        )

    return public_key, secret_key


def generate_webhook_secret():
    return secrets.token_urlsafe(32)


def ensure_sandbox_wallet(merchant):
    """Create an isolated sandbox wallet for a merchant if missing."""
    if merchant.sandbox_wallet_id:
        return merchant.sandbox_wallet

    with transaction.atomic():
        merchant = Merchant.objects.select_for_update().get(pk=merchant.pk)
        if merchant.sandbox_wallet_id:
            return merchant.sandbox_wallet

        sandbox_user = User.objects.create_user(
            email=f'sandbox-merchant-{merchant.id}@wallet.internal',
            handle=f'sandbox_m{merchant.id}',
            display_name=f'{merchant.business_name} Sandbox',
        )
        sandbox_wallet = Wallet.objects.create(
            user=sandbox_user,
            currency=merchant.wallet.currency,
            status=WalletStatus.ACTIVE,
            is_sandbox=True,
        )
        merchant.sandbox_wallet = sandbox_wallet
        merchant.save(update_fields=['sandbox_wallet'])
        return sandbox_wallet


def ensure_merchant_api_keys_on_activation(merchant):
    """Generate live/sandbox keys when a merchant goes active, if missing."""
    results = {}
    for mode in (MerchantMode.LIVE, MerchantMode.SANDBOX):
        if not MerchantApiKey.objects.filter(merchant=merchant, mode=mode, is_active=True).exists():
            results[mode] = generate_merchant_api_keys(merchant, mode)
        if mode == MerchantMode.SANDBOX:
            ensure_sandbox_wallet(merchant)
    if not merchant.webhook_secret:
        merchant.webhook_secret = generate_webhook_secret()
        merchant.save(update_fields=['webhook_secret'])
    return results


def get_merchant_wallet(merchant, mode):
    if mode == MerchantMode.SANDBOX:
        return ensure_sandbox_wallet(merchant)
    return merchant.wallet
