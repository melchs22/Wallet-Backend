from rest_framework.throttling import UserRateThrottle


class SustainableUserRateThrottle(UserRateThrottle):
    """Apply the user limit with a versioned key after the rate policy changes."""

    cache_key_version = 'v2'

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return f'throttle_user_{self.cache_key_version}_{request.user.pk}'