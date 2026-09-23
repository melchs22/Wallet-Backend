import json
import logging
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from wallet.models import ExchangeRate, SupportedCountry, Wallet

logger = logging.getLogger(__name__)

PRIMARY_SOURCE = 'exchangerate.fun'


def get_active_currencies():
    """Currencies the system should maintain rates for."""
    wallet_currencies = set(
        Wallet.objects.values_list('currency', flat=True).distinct()
    )
    country_currencies = set(
        SupportedCountry.objects.filter(active=True)
        .exclude(currency__isnull=True)
        .exclude(currency='')
        .values_list('currency', flat=True)
    )
    extra = set(getattr(settings, 'EXCHANGE_RATE_EXTRA_CURRENCIES', ['GNF', 'EUR', 'GBP']))
    currencies = (
        {c.upper() for c in wallet_currencies if c}
        | {c.upper() for c in country_currencies if c}
        | {c.upper() for c in extra if c}
    )
    return sorted(currencies)


def fetch_latest_rates(base_currency):
    """
    Fetch latest rates, falling back to the configured secondary provider.
    Returns dict with keys: base, timestamp, rates.
    """
    base_currency = base_currency.upper()
    timeout = getattr(settings, 'EXCHANGE_RATE_API_TIMEOUT', 15)
    providers = (
        (
            PRIMARY_SOURCE,
            getattr(settings, 'EXCHANGE_RATE_API_URL',
                    'https://api.exchangerate.fun/latest'),
            'base',
        ),
        (
            'frankfurter.app',
            getattr(settings, 'EXCHANGE_RATE_FALLBACK_URL',
                    'https://api.frankfurter.app/latest'),
            'from',
        ),
    )
    errors = []
    for source, api_url, base_param in providers:
        if not api_url:
            continue
        try:
            response = requests.get(
                f'{api_url.rstrip("/")}?{base_param}={base_currency}',
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            returned_base = (data.get('base') or data.get('from') or '').upper()
            if returned_base != base_currency:
                raise ValueError(
                    f'API returned unexpected base currency: {returned_base or None}'
                )
            rates = data.get('rates')
            if not isinstance(rates, dict) or not rates:
                raise ValueError('API response missing rates')
            return {
                'base': base_currency,
                'timestamp': data.get('timestamp') or data.get('date'),
                'source': source,
                'rates': {k.upper(): v for k, v in rates.items()},
            }
        except (requests.RequestException, ValueError, TypeError) as exc:
            errors.append(f'{source}: {exc}')
            logger.warning(
                'exchange_rate_provider_failed',
                extra={'provider': source, 'base': base_currency, 'error': str(exc)},
            )

    raise RuntimeError(
        f'All exchange-rate providers failed for {base_currency}: '
        + '; '.join(errors)
    )


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


def refresh_exchange_rates(base_currencies=None, target_currencies=None):
    """
    Pull fresh rates from exchangerate.fun and replace the rate table.

    Fetch and validate the complete matrix before changing the database. This
    means a provider outage or incomplete response cannot leave a mixture of
    stale and fresh rows (or be reported as a successful refresh).
    """
    targets = sorted({c.upper() for c in (target_currencies or get_active_currencies())})
    bases = sorted({c.upper() for c in (base_currencies or targets)})

    if not bases:
        bases = ['GNF']
        targets = ['GNF', 'EUR', 'GBP']

    now = timezone.now()
    fetched_payloads = {}

    for base in bases:
        try:
            payload = fetch_latest_rates(base)
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            logger.error('exchange_rate_fetch_failed', extra={'base': base, 'error': str(exc)})
            raise RuntimeError(f'Unable to refresh exchange rates for {base}: {exc}') from exc

        fetched_payloads[base] = payload

    new_rates = []
    for base, payload in fetched_payloads.items():
        for target in targets:
            if target == base:
                continue
            raw_rate = payload['rates'].get(target)
            if raw_rate is None:
                reverse_rates = fetched_payloads.get(target, {}).get('rates', {})
                reverse_rate = reverse_rates.get(base)
                if reverse_rate is not None:
                    try:
                        raw_rate = Decimal('1') / Decimal(str(reverse_rate))
                    except (InvalidOperation, ZeroDivisionError):
                        raw_rate = None
            if raw_rate is None:
                raise RuntimeError(
                    f'Exchange-rate provider did not return {base}/{target}'
                )

            try:
                rate = Decimal(str(raw_rate))
            except (InvalidOperation, TypeError):
                raise RuntimeError(f'Invalid exchange rate for {base}/{target}') from None

            if rate <= 0:
                raise RuntimeError(f'Invalid exchange rate for {base}/{target}')

            new_rates.append(ExchangeRate(
                from_currency=base,
                to_currency=target,
                rate=rate,
                source=payload.get('source', PRIMARY_SOURCE),
                valid_from=now,
                valid_until=None,
            ))

    with transaction.atomic():
        ExchangeRate.objects.all().delete()
        ExchangeRate.objects.bulk_create(new_rates)

    result = {
        'run_at': now.isoformat(),
        'bases_fetched': len(bases),
        'created_count': len(new_rates),
        'replaced_count': len(new_rates),
        'skipped_count': 0,
        'missing_pairs': [],
        'errors': [],
        'status': 'ok',
    }
    logger.info(json.dumps({'event': 'refresh_exchange_rates', **result}))
    return result
