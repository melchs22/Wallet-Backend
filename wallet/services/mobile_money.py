import logging

from django.db import transaction
from django.utils import timezone

from wallet.models import (
    AuditLog,
    LedgerDirection,
    LedgerEntry,
    MobileMoneyTransaction,
    MobileMoneyTransactionStatus,
    MobileMoneyTransactionType,
    Transaction,
    TransactionStatus,
    TransactionType,
)
from wallet.services.notifications import create_notification_record

logger = logging.getLogger(__name__)


def process_mobile_money_webhook_event(provider_transaction_id, status, provider_response=None):
    """
    Process a mobile money provider webhook event idempotently.
    Safe to run twice for the same provider_transaction_id + terminal status.
    """
    provider_response = provider_response or {}

    with transaction.atomic():
        mm_transaction = MobileMoneyTransaction.objects.select_for_update().get(
            provider_transaction_id=provider_transaction_id
        )

        if mm_transaction.status in (
            MobileMoneyTransactionStatus.COMPLETED,
            MobileMoneyTransactionStatus.FAILED,
            MobileMoneyTransactionStatus.CANCELLED,
        ):
            logger.info(
                'mobile_money_webhook_already_processed',
                extra={
                    'provider_transaction_id': provider_transaction_id,
                    'status': mm_transaction.status,
                },
            )
            return {'status': 'already_processed', 'mm_transaction_id': mm_transaction.id}

        if status == 'completed':
            mm_transaction.status = MobileMoneyTransactionStatus.COMPLETED
            mm_transaction.completed_at = timezone.now()
            mm_transaction.provider_response = provider_response

            if mm_transaction.type == MobileMoneyTransactionType.TOPUP:
                transaction_obj = Transaction.objects.create(
                    type=TransactionType.TOPUP,
                    sender=None,
                    recipient=mm_transaction.user,
                    amount=mm_transaction.amount,
                    currency=mm_transaction.currency,
                    note=f'Mobile Money Top-up via {mm_transaction.linked_provider.provider}',
                    status=TransactionStatus.COMPLETED,
                )
                LedgerEntry.objects.create(
                    wallet=mm_transaction.wallet,
                    transaction=transaction_obj,
                    direction=LedgerDirection.CREDIT,
                    amount=mm_transaction.amount,
                )

        elif status == 'failed':
            mm_transaction.status = MobileMoneyTransactionStatus.FAILED
            mm_transaction.failure_reason = provider_response.get('reason', 'Unknown error')
            mm_transaction.provider_response = provider_response

            if mm_transaction.type == MobileMoneyTransactionType.WITHDRAWAL:
                LedgerEntry.objects.filter(
                    wallet=mm_transaction.wallet,
                    transaction=None,
                    direction=LedgerDirection.DEBIT,
                    amount=mm_transaction.amount,
                ).delete()
        else:
            raise ValueError(f'Unsupported webhook status: {status}')

        mm_transaction.save()

        AuditLog.objects.create(
            user=mm_transaction.user,
            action='mobile_money_webhook_received',
            metadata={
                'mm_transaction_id': mm_transaction.id,
                'provider_transaction_id': provider_transaction_id,
                'status': status,
                'provider': mm_transaction.linked_provider.provider,
            },
        )

        notification_type = (
            'mobile_money_transaction_completed'
            if status == 'completed'
            else 'mobile_money_transaction_failed'
        )
        create_notification_record(
            mm_transaction.user,
            notification_type,
            {
                'mm_transaction_id': mm_transaction.id,
                'type': mm_transaction.type,
                'amount': str(mm_transaction.amount),
                'currency': mm_transaction.currency,
                'status': status,
            },
        )

    try:
        from wallet.tasks import send_notification_task
        notification = mm_transaction.user.notifications.order_by('-created_at').first()
        if notification:
            send_notification_task.delay(notification.id)
    except Exception:
        logger.exception('mobile_money_notification_dispatch_failed')

    return {'status': 'processed', 'mm_transaction_id': mm_transaction.id}
