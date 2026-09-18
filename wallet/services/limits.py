from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.db.models import Count, Sum
from django.utils import timezone

from wallet.models import (
    KYCTier, MerchantLimit, PaymentIntentStatus, SystemSetting,
    TransactionStatus, TransactionStatus as TxStatus,
)

BUSINESS_TIMEZONE = ZoneInfo('Africa/Conakry')
MERCHANT_LIMIT_STATUSES = [
    PaymentIntentStatus.CREATED,
    PaymentIntentStatus.PENDING_PAYMENT,
    PaymentIntentStatus.SUCCEEDED,
]


DEFAULTS = {
    'max_single_transfer_limit': '1000000.00',
    'max_daily_transfer_limit': '500000000.00',
    'usage_transfers_per_step': '5',
    'usage_volume_per_step': '50000.00',
    'usage_per_tx_increase': '500.00',
    'usage_daily_increase': '2500.00',
    'usage_max_steps': '10',
    'kyc_tier_1_per_tx_bonus': '2000.00',
    'kyc_tier_1_daily_bonus': '10000.00',
    'kyc_tier_2_per_tx_bonus': '10000.00',
    'kyc_tier_2_daily_bonus': '50000.00',
}


def get_setting(key, default=None):
    fallback = default if default is not None else DEFAULTS.get(key, '')
    try:
        return SystemSetting.objects.get(key=key).value
    except SystemSetting.DoesNotExist:
        return fallback


def get_decimal_setting(key, default=None):
    raw = get_setting(key, default)
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        fallback = default if default is not None else DEFAULTS.get(key, '0')
        return Decimal(str(fallback))


def get_int_setting(key, default=None):
    raw = get_setting(key, default)
    try:
        return max(int(Decimal(str(raw))), 0)
    except (InvalidOperation, TypeError, ValueError):
        fallback = default if default is not None else DEFAULTS.get(key, '0')
        return max(int(Decimal(str(fallback))), 0)


def _kyc_bonuses(kyc_tier):
    if kyc_tier == KYCTier.TIER_2:
        return (
            get_decimal_setting('kyc_tier_2_per_tx_bonus'),
            get_decimal_setting('kyc_tier_2_daily_bonus'),
        )
    if kyc_tier == KYCTier.TIER_1:
        return (
            get_decimal_setting('kyc_tier_1_per_tx_bonus'),
            get_decimal_setting('kyc_tier_1_daily_bonus'),
        )
    return Decimal('0.00'), Decimal('0.00')


def compute_limit_snapshot(user):
    # Calculate total completed transactions and volume (for usage-based limits)
    usage = user.sent_transactions.filter(status=TransactionStatus.COMPLETED).aggregate(
        completed=Count('id'),
        volume=Sum('amount'),
    )
    completed = usage['completed'] or 0
    volume = usage['volume'] or Decimal('0.00')

    transfers_per_step = max(get_int_setting('usage_transfers_per_step'), 1)
    volume_per_step = get_decimal_setting('usage_volume_per_step')
    max_steps = get_int_setting('usage_max_steps')

    count_steps = completed // transfers_per_step
    volume_steps = int(volume // volume_per_step) if volume_per_step > 0 else 0
    step = min(max(count_steps, volume_steps), max_steps)

    transfers_into_step = completed % transfers_per_step
    transfers_until_next = 0 if step >= max_steps else transfers_per_step - transfers_into_step

    base_per_tx = get_decimal_setting('max_single_transfer_limit')
    base_daily = get_decimal_setting('max_daily_transfer_limit')
    per_tx_increase = get_decimal_setting('usage_per_tx_increase')
    daily_increase = get_decimal_setting('usage_daily_increase')
    kyc_per_tx, kyc_daily = _kyc_bonuses(user.kyc_tier)

    per_tx = base_per_tx + (per_tx_increase * step) + kyc_per_tx
    daily = base_daily + (daily_increase * step) + kyc_daily
    next_step = min(step + 1, max_steps)
    next_per_tx = base_per_tx + (per_tx_increase * next_step) + kyc_per_tx
    next_daily = base_daily + (daily_increase * next_step) + kyc_daily

    return {
        'completed_transfers': completed,
        'volume_sent': volume,
        'current_step': step,
        'max_steps': max_steps,
        'transfers_per_step': transfers_per_step,
        'transfers_until_next_increase': transfers_until_next,
        'per_tx_increase': per_tx_increase,
        'daily_increase': daily_increase,
        'send_limit_per_tx': per_tx,
        'send_limit_daily': daily,
        'next_send_limit_per_tx': next_per_tx,
        'next_send_limit_daily': next_daily,
        'manually_set': bool(getattr(user, 'limits_manually_set', False)),
    }


def get_daily_sent_amount(user):
    """Get the total amount sent by the user today (resets at midnight)."""
    from django.db.models import Sum
    
    # Get start of today in the business timezone
    now = timezone.now()
    start_of_today = now.astimezone(BUSINESS_TIMEZONE).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    
    # Calculate total sent today
    sent_today = user.sent_transactions.filter(
        created_at__gte=start_of_today,
        status=TransactionStatus.COMPLETED
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    return sent_today


def get_daily_remaining(user):
    """Get the remaining daily limit for the user (resets at midnight)."""
    daily_limit = user.send_limit_daily
    sent_today = get_daily_sent_amount(user)
    remaining = max(daily_limit - sent_today, Decimal('0.00'))
    return remaining


def apply_usage_based_limits(user):
    """Raise stored send limits from usage and KYC unless an admin locked them."""
    snapshot = compute_limit_snapshot(user)
    if snapshot['manually_set']:
        return snapshot
    fields = []
    if user.send_limit_per_tx != snapshot['send_limit_per_tx']:
        user.send_limit_per_tx = snapshot['send_limit_per_tx']
        fields.append('send_limit_per_tx')
    if user.send_limit_daily != snapshot['send_limit_daily']:
        user.send_limit_daily = snapshot['send_limit_daily']
        fields.append('send_limit_daily')
    if fields:
        user.save(update_fields=fields)
    return snapshot


def get_merchant_limit(merchant, currency):
    currency = currency.upper()
    limit, _ = MerchantLimit.objects.get_or_create(merchant=merchant, currency=currency)
    return limit


def merchant_limit_snapshot(merchant, currency, now=None):
    """Return merchant limits and period usage for the requested currency."""
    now = now or timezone.now()
    limit = get_merchant_limit(merchant, currency)
    local_now = now.astimezone(BUSINESS_TIMEZONE)
    start_day = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_month = start_day.replace(day=1)
    intents = merchant.payment_intents.filter(
        currency=limit.currency, status__in=MERCHANT_LIMIT_STATUSES,
    )
    daily_used = intents.filter(created_at__gte=start_day).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    monthly_used = intents.filter(created_at__gte=start_month).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    return {
        'currency': limit.currency,
        'per_transaction': limit.per_transaction,
        'per_transaction_used': Decimal('0.00'),
        'per_transaction_remaining': limit.per_transaction,
        'daily': limit.daily,
        'monthly': limit.monthly,
        'daily_used': daily_used,
        'daily_remaining': max(limit.daily - daily_used, Decimal('0.00')),
        'monthly_used': monthly_used,
        'monthly_remaining': max(limit.monthly - monthly_used, Decimal('0.00')),
    }


def enforce_merchant_limit(merchant, amount, currency):
    snapshot = merchant_limit_snapshot(merchant, currency)
    if amount > snapshot['per_transaction']:
        raise ValueError('per_transaction_limit_exceeded')
    if snapshot['daily_used'] + amount > snapshot['daily']:
        raise ValueError('daily_limit_exceeded')
    if snapshot['monthly_used'] + amount > snapshot['monthly']:
        raise ValueError('monthly_limit_exceeded')
    return snapshot
