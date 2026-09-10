from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from wallet.models import FeeAppliesTo, FeePolicy, FeeWaiver, Merchant, TransferFeeRule, User


def get_platform_wallet(currency='GNF', is_sandbox=False):
    from wallet.models import Wallet, WalletStatus

    email = 'platform-sandbox@wallet.internal' if is_sandbox else 'platform@wallet.internal'
    handle = 'platform_sandbox' if is_sandbox else 'platform'
    user, _ = User.objects.get_or_create(
        email=email,
        defaults={
            'handle': handle,
            'display_name': 'Platform Sandbox' if is_sandbox else 'Platform',
            'is_staff': True,
            'is_active': True,
        },
    )
    wallet, _ = Wallet.objects.get_or_create(
        user=user,
        defaults={'currency': currency, 'status': WalletStatus.ACTIVE, 'is_sandbox': is_sandbox},
    )
    return wallet


def _has_active_waiver(user, applies_to):
    now = timezone.now()
    return FeeWaiver.objects.filter(
        user=user,
        applies_to=applies_to,
        valid_from__lte=now,
    ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=now)).exists()


def resolve_fee(amount, applies_to, *, merchant=None, user=None, currency='GNF'):
    """
    Resolve applicable fee for a transfer. Merchant-scoped policies outrank general ones.
    Returns (fee_amount, policy_or_none).
    """
    if user and _has_active_waiver(user, applies_to):
        return Decimal('0.00'), None

    policies = FeePolicy.objects.filter(is_active=True, applies_to=applies_to)
    if currency:
        policies = policies.filter(Q(currency='') | Q(currency=currency))

    if merchant:
        merchant_policy = policies.filter(merchant=merchant).order_by('-priority').first()
        if merchant_policy:
            return _calculate_fee(amount, merchant_policy), merchant_policy

    general_policy = policies.filter(merchant__isnull=True).order_by('-priority').first()
    if general_policy:
        return _calculate_fee(amount, general_policy), general_policy

    return Decimal('0.00'), None


def _calculate_fee(amount, policy):
    fee = Decimal('0.00')
    if policy.fee_fixed:
        fee += policy.fee_fixed
    if policy.fee_percent:
        fee += (amount * policy.fee_percent / Decimal('100')).quantize(Decimal('0.01'))
    return fee


def resolve_withdrawal_fee(amount, currency='GNF'):
    """Resolve the admin-editable amount-band fee schedule for withdrawals."""
    if currency != 'GNF':
        return Decimal('0.00'), None
    rule = TransferFeeRule.objects.filter(active=True, min_amount__lte=amount).filter(
        Q(max_amount__isnull=True) | Q(max_amount__gte=amount)
    ).order_by('-min_amount').first()
    if not rule:
        return Decimal('0.00'), None
    if rule.fee_type == TransferFeeRule.FeeType.FLAT:
        return rule.fee_value.quantize(Decimal('0.01')), rule
    return (amount * rule.fee_value / Decimal('100')).quantize(Decimal('0.01')), rule


def preview_merchant_transfer_fee(amount, merchant_id, currency='GNF'):
    merchant = Merchant.objects.get(pk=merchant_id)
    fee_amount, policy = resolve_fee(
        amount,
        FeeAppliesTo.MERCHANT_TRANSFER,
        merchant=merchant,
        user=merchant.user,
        currency=currency,
    )
    total = amount + fee_amount
    return {
        'amount': str(amount),
        'fee_amount': str(fee_amount),
        'total_amount': str(total),
        'currency': currency,
        'fee_policy_id': policy.id if policy else None,
    }
