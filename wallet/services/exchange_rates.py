import json
import logging
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from wallet.models import ExchangeRate, Wallet

logger = logging.getLogger(__name__)

SOURCE = 'exchangerate.fun'


def get_active_currencies():
    """Currencies the system should maintain rates for."""
    wallet_currencies = set(
        Wallet.objects.values_list('currency', flat=True).distinct()
    )
    extra = set(getattr(settings, 'EXCHANGE_RATE_EXTRA_CURRENCIES', ['USD', 'EUR', 'GBP']))
    currencies = {c.upper() for c in wallet_currencies if c} | extra
    return sorted(currencies)


def fetch_latest_rates(base_currency):
    """
    Fetch latest rates from exchangerate.fun for a base currency.
    Returns dict with keys: base, timestamp, rates.
    """
    base_currency = base_currency.upper()
    api_url = getattr(settings, 'EXCHANGE_RATE_API_URL', 'https://api.exchangerate.fun/latest')
    url = f'{api_url.rstrip("/")}?base={base_currency}'
    timeout = getattr(settings, 'EXCHANGE_RATE_API_TIMEOUT', 15)

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    data = response.json()

    if data.get('base', '').upper() != base_currency:
        raise ValueError(f'API returned unexpected base currency: {data.get("base")}')

    rates = data.get('rates')
    if not isinstance(rates, dict) or not rates:
        raise ValueError('API response missing rates')

    return {
        'base': base_currency,
        'timestamp': data.get('timestamp'),
        'rates': {k.upper(): v for k, v in rates.items()},
    }


def get_active_exchange_rate(from_currency, to_currency, at=None):
    """Return the current active ExchangeRate row for a currency pair."""
    at = at or timezone.now()
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if from_currency == to_currency:
        return None

    return (
        ExchangeRate.objects.filter(
            from_currency=from_currency,
            to_currency=to_currency,
            valid_from__lte=at,
        )
        .filter(Q(valid_until__gte=at) | Q(valid_until__isnull=True))
        .order_by('-valid_from')
        .first()
    )


@transaction.atomic
def _store_rate(from_currency, to_currency, rate, valid_from):
    """Close the previous active rate and append a new historical row."""
    ExchangeRate.objects.filter(
        from_currency=from_currency,
        to_currency=to_currency,
        valid_until__isnull=True,
    ).update(valid_until=valid_from)

    return ExchangeRate.objects.create(
        from_currency=from_currency,
        to_currency=to_currency,
        rate=rate,
        source=SOURCE,
        valid_from=valid_from,
        valid_until=None,
    )


def refresh_exchange_rates(base_currencies=None, target_currencies=None):
    """
    Pull fresh rates from exchangerate.fun and write new ExchangeRate rows.
    Never updates existing rows — closes the prior active rate and inserts a new one.
    """
    targets = sorted({c.upper() for c in (target_currencies or get_active_currencies())})
    bases = sorted({c.upper() for c in (base_currencies or targets)})

    if not bases:
        bases = ['USD']
        targets = ['USD', 'EUR', 'GBP']

    now = timezone.now()
    created_count = 0
    skipped_count = 0
    errors = []

    for base in bases:
        try:
            payload = fetch_latest_rates(base)
        except (requests.RequestException, ValueError) as exc:
            logger.error('exchange_rate_fetch_failed', extra={'base': base, 'error': str(exc)})
            errors.append({'base': base, 'error': str(exc)})
            continue

        api_rates = payload['rates']

        for target in targets:
            if target == base:
                continue
            if target not in api_rates:
                skipped_count += 1
                continue

            try:
                rate = Decimal(str(api_rates[target]))
            except (InvalidOperation, TypeError):
                skipped_count += 1
                continue

            if rate <= 0:
                skipped_count += 1
                continue

            _store_rate(base, target, rate, now)
            created_count += 1

    result = {
        'run_at': now.isoformat(),
        'bases_fetched': len(bases) - len(errors),
        'created_count': created_count,
        'skipped_count': skipped_count,
        'errors': errors,
        'status': 'partial_failure' if errors else 'ok',
    }

    logger.info(json.dumps({'event': 'refresh_exchange_rates', **result}))
    return result
