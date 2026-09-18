"""Merchant API key authentication."""

from django.contrib.auth.hashers import check_password
from rest_framework import authentication, exceptions, throttling

from wallet.models import MerchantApiKey, MerchantMode, MerchantStatus


class MerchantApiKeyAuthentication(authentication.BaseAuthentication):
    keyword = 'Bearer'

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header:
            return None
        if header[0].lower() != self.keyword.lower().encode() or len(header) != 2:
            raise exceptions.AuthenticationFailed('Use Authorization: Bearer <merchant secret key>.')

        raw_key = header[1].decode('utf-8')
        if not (raw_key.startswith('sk_live_') or raw_key.startswith('sk_test_')):
            raise exceptions.AuthenticationFailed('Invalid merchant API key format.')

        mode = MerchantMode.LIVE if raw_key.startswith('sk_live_') else MerchantMode.SANDBOX
        prefix = raw_key[:20]
        api_key = (
            MerchantApiKey.objects.select_related('merchant', 'merchant__user')
            .filter(secret_key_prefix=prefix, is_active=True, mode=mode)
            .first()
        )
        if api_key is None or not check_password(raw_key, api_key.secret_key_hash):
            raise exceptions.AuthenticationFailed('Invalid API key')

        merchant = api_key.merchant
        # Sandbox integrations are available while compliance reviews are pending.
        if merchant.status != MerchantStatus.ACTIVE and mode == MerchantMode.LIVE:
            raise exceptions.AuthenticationFailed('Merchant account is not active')

        request.merchant_api_mode = mode
        request.merchant_api_key = api_key
        return (merchant.user, api_key)

    def authenticate_header(self, request):
        return self.keyword


class MerchantApiKeyRateThrottle(throttling.SimpleRateThrottle):
    scope = 'merchant_api'

    def get_cache_key(self, request, view):
        api_key = getattr(request, 'merchant_api_key', None)
        if api_key is None:
            return None
        return self.cache_format % {'ident': api_key.public_key}
