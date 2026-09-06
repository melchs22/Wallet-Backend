import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from wallet.models import (
    AuditLog,
    FeeAppliesTo,
    LedgerDirection,
    LedgerEntry,
    MerchantMode,
    MerchantStatus,
    PaymentIntent,
    PaymentIntentStatus,
    ProcessedRequest,
    Transaction,
    TransactionStatus,
    TransactionType,
    User,
    UserStatus,
    Wallet,
    WalletStatus,
)
from wallet.services.fees import get_platform_wallet, resolve_fee
from wallet.services.merchants import get_merchant_wallet
from wallet.services.notifications import create_notification_record
from wallet.services.webhooks import enqueue_payment_intent_webhook

logger = logging.getLogger(__name__)


class PaymentIntentError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def checkout_url_for_intent(intent):
    base = getattr(settings, 'FRONTEND_ORIGIN_URL', 'https://dsd-wallet.vercel.app')
    return f'{base.rstrip("/")}/checkout/{intent.id}'


def create_payment_intent(merchant, *, amount, currency, external_reference='', description='', mode, return_url=''):
    if merchant.status != MerchantStatus.ACTIVE:
        raise PaymentIntentError('merchant_not_active', 'Merchant account is not active')

    intent = PaymentIntent.objects.create(
        merchant=merchant,
        amount=amount,
        currency=currency,
        external_reference=external_reference,
        description=description,
        mode=mode,
        return_url=return_url,
        status=PaymentIntentStatus.CREATED,
    )
    intent.status = PaymentIntentStatus.PENDING_PAYMENT
    intent.save(update_fields=['status'])
    return intent


def cancel_payment_intent(intent):
    if intent.status not in (PaymentIntentStatus.CREATED, PaymentIntentStatus.PENDING_PAYMENT):
        raise PaymentIntentError('invalid_status', f'Cannot cancel intent in status {intent.status}')

    intent.status = PaymentIntentStatus.CANCELLED
    intent.save(update_fields=['status'])
    enqueue_payment_intent_webhook(intent, 'payment_intent.cancelled')
    return intent


def expire_payment_intents():
    now = timezone.now()
    expired_qs = PaymentIntent.objects.filter(
        status__in=[PaymentIntentStatus.CREATED, PaymentIntentStatus.PENDING_PAYMENT],
        expires_at__lt=now,
    )
    expired_ids = list(expired_qs.values_list('id', flat=True))
    count = expired_qs.update(status=PaymentIntentStatus.EXPIRED)

    for intent_id in expired_ids:
        intent = PaymentIntent.objects.get(pk=intent_id)
        enqueue_payment_intent_webhook(intent, 'payment_intent.expired')

    return {'expired_count': count, 'payment_intent_ids': expired_ids}


def get_checkout_public_detail(intent):
    return {
        'id': intent.id,
        'merchant_name': intent.merchant.business_name,
        'amount': str(intent.amount),
        'currency': intent.currency,
        'description': intent.description,
        'status': intent.status,
        'mode': intent.mode,
        'expires_at': intent.expires_at.isoformat(),
        'return_url': intent.return_url,
    }


def _get_payer_wallet(payer, currency, is_sandbox):
    if is_sandbox:
        sandbox_email = f'sandbox-payer-{payer.id}@wallet.internal'
        sandbox_user, _ = User.objects.get_or_create(
            email=sandbox_email,
            defaults={
                'handle': f'sandbox_p{payer.id}',
                'display_name': f'{payer.handle} Sandbox',
            },
        )
        wallet, _ = Wallet.objects.get_or_create(
            user=sandbox_user,
            defaults={'currency': currency, 'status': WalletStatus.ACTIVE, 'is_sandbox': True},
        )
        return wallet
    wallet = payer.wallet
    if wallet.currency != currency:
        raise PaymentIntentError('currency_mismatch', 'Wallet currency does not match payment intent')
    return wallet


def confirm_payment_intent(intent, payer, idempotency_key):
    if intent.status not in (PaymentIntentStatus.CREATED, PaymentIntentStatus.PENDING_PAYMENT):
        raise PaymentIntentError('invalid_status', f'Payment intent is {intent.status}')

    if intent.expires_at < timezone.now():
        intent.status = PaymentIntentStatus.EXPIRED
        intent.save(update_fields=['status'])
        raise PaymentIntentError('expired', 'Payment intent has expired')

    if payer.status != UserStatus.ACTIVE:
        raise PaymentIntentError('payer_suspended', 'Payer account is suspended')

    is_sandbox = intent.mode == MerchantMode.SANDBOX
    merchant_wallet = get_merchant_wallet(intent.merchant, intent.mode)
    payer_wallet = _get_payer_wallet(payer, intent.currency, is_sandbox)

    if payer_wallet.status != WalletStatus.ACTIVE or merchant_wallet.status != WalletStatus.ACTIVE:
        raise PaymentIntentError('wallet_frozen', 'Wallet is frozen')

    existing = ProcessedRequest.objects.filter(idempotency_key=idempotency_key).select_related('transaction').first()
    if existing and existing.transaction:
        intent.refresh_from_db()
        return existing.transaction

    fee_amount, _ = resolve_fee(
        intent.amount,
        FeeAppliesTo.MERCHANT_TRANSFER,
        merchant=intent.merchant,
        user=intent.merchant.user,
        currency=intent.currency,
    )
    total_debit = intent.amount + fee_amount
    platform_wallet = get_platform_wallet(intent.currency, is_sandbox=is_sandbox)

    with transaction.atomic():
        intent = PaymentIntent.objects.select_for_update().get(pk=intent.pk)
        if intent.status not in (PaymentIntentStatus.CREATED, PaymentIntentStatus.PENDING_PAYMENT):
            raise PaymentIntentError('invalid_status', f'Payment intent is {intent.status}')

        payer_wallet = Wallet.objects.select_for_update().get(pk=payer_wallet.pk)
        balance = payer_wallet.get_balance()
        if balance < total_debit:
            raise PaymentIntentError('insufficient_funds', 'Insufficient funds')

        if not is_sandbox:
            twenty_four_hours_ago = timezone.now() - timedelta(days=1)
            sent_today = payer.sent_transactions.filter(
                created_at__gte=twenty_four_hours_ago,
                status=TransactionStatus.COMPLETED,
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
            if sent_today + total_debit > payer.send_limit_daily:
                raise PaymentIntentError('daily_limit_exceeded', 'Daily limit exceeded')
            if total_debit > payer.send_limit_per_tx:
                raise PaymentIntentError('per_transaction_limit_exceeded', 'Per-transaction limit exceeded')

        transaction_obj = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=payer,
            recipient=intent.merchant.user,
            amount=intent.amount,
            currency=intent.currency,
            note=intent.description or f'Payment to {intent.merchant.business_name}',
            status=TransactionStatus.COMPLETED,
        )

        LedgerEntry.objects.create(
            wallet=payer_wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.DEBIT,
            amount=total_debit,
        )
        LedgerEntry.objects.create(
            wallet=merchant_wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.CREDIT,
            amount=intent.amount,
        )
        if fee_amount > 0:
            LedgerEntry.objects.create(
                wallet=platform_wallet,
                transaction=transaction_obj,
                direction=LedgerDirection.CREDIT,
                amount=fee_amount,
            )

        ProcessedRequest.objects.create(
            idempotency_key=idempotency_key,
            user=payer,
            transaction=transaction_obj,
        )

        intent.status = PaymentIntentStatus.SUCCEEDED
        intent.payer = payer
        intent.resulting_transaction = transaction_obj
        intent.save(update_fields=['status', 'payer', 'resulting_transaction'])

        AuditLog.objects.create(
            user=payer,
            action='merchant_payment_confirmed',
            metadata={
                'payment_intent_id': intent.id,
                'transaction_id': str(transaction_obj.id),
                'merchant_id': intent.merchant_id,
                'amount': str(intent.amount),
                'fee_amount': str(fee_amount),
                'mode': intent.mode,
            },
        )

    create_notification_record(
        intent.merchant.user,
        'merchant_payment_received',
        {
            'payment_intent_id': intent.id,
            'amount': str(intent.amount),
            'currency': intent.currency,
            'payer_handle': payer.handle,
        },
    )

    transaction.on_commit(lambda: enqueue_payment_intent_webhook(intent, 'payment_intent.succeeded'))
    return transaction_obj
