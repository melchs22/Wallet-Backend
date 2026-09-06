import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from wallet.models import (
    AuditLog,
    LedgerDirection,
    LedgerEntry,
    ProcessedRequest,
    ScheduledTransfer,
    ScheduledTransferStatus,
    ScheduleFrequency,
    Transaction,
    TransactionStatus,
    TransactionType,
    UserStatus,
    Wallet,
    WalletStatus,
)
from wallet.services.notifications import create_notification_record

logger = logging.getLogger(__name__)


class TransferExecutionError(Exception):
    def __init__(self, reason, message):
        self.reason = reason
        self.message = message
        super().__init__(message)


def execute_p2p_transfer(
    sender,
    recipient,
    amount,
    currency,
    note='',
    idempotency_key=None,
    *,
    skip_limit_checks=False,
):
    """
    Atomic same-currency P2P transfer used by scheduled transfers and other background jobs.
    Returns the Transaction on success; raises TransferExecutionError on failure.
    """
    if idempotency_key is None:
        idempotency_key = f'p2p-{uuid.uuid4()}'

    existing = ProcessedRequest.objects.filter(idempotency_key=idempotency_key).select_related('transaction').first()
    if existing and existing.transaction:
        return existing.transaction

    if sender.status != UserStatus.ACTIVE:
        raise TransferExecutionError('sender_account_suspended', 'Sender account is suspended')
    if recipient.status != UserStatus.ACTIVE:
        raise TransferExecutionError('recipient_account_suspended', 'Recipient account is suspended')

    sender_wallet = sender.wallet
    recipient_wallet = recipient.wallet

    if sender_wallet.status != WalletStatus.ACTIVE:
        raise TransferExecutionError('sender_wallet_frozen', 'Sender wallet is frozen')
    if recipient_wallet.status != WalletStatus.ACTIVE:
        raise TransferExecutionError('recipient_wallet_frozen', 'Recipient wallet is frozen')
    if sender_wallet.currency != currency or recipient_wallet.currency != currency:
        raise TransferExecutionError('currency_mismatch', 'Wallet currency mismatch')

    with transaction.atomic():
        sender_wallet = Wallet.objects.select_for_update().get(pk=sender_wallet.pk)

        current_balance = sender_wallet.get_balance()
        if current_balance < amount:
            raise TransferExecutionError('insufficient_funds', 'Insufficient funds')

        if not skip_limit_checks:
            if amount > sender.send_limit_per_tx:
                raise TransferExecutionError('per_transaction_limit_exceeded', 'Per-transaction limit exceeded')

            twenty_four_hours_ago = timezone.now() - timedelta(days=1)
            sent_today = sender.sent_transactions.filter(
                created_at__gte=twenty_four_hours_ago,
                status=TransactionStatus.COMPLETED,
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

            if sent_today + amount > sender.send_limit_daily:
                raise TransferExecutionError('daily_limit_exceeded', 'Daily limit exceeded')

        transaction_obj = Transaction.objects.create(
            type=TransactionType.P2P_TRANSFER,
            sender=sender,
            recipient=recipient,
            amount=amount,
            currency=currency,
            note=note,
            status=TransactionStatus.COMPLETED,
        )

        LedgerEntry.objects.create(
            wallet=sender_wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.DEBIT,
            amount=amount,
        )
        LedgerEntry.objects.create(
            wallet=recipient_wallet,
            transaction=transaction_obj,
            direction=LedgerDirection.CREDIT,
            amount=amount,
        )

        ProcessedRequest.objects.create(
            idempotency_key=idempotency_key,
            user=sender,
            transaction=transaction_obj,
        )

        AuditLog.objects.create(
            user=sender,
            action='p2p_transfer',
            metadata={
                'transaction_id': str(transaction_obj.id),
                'recipient_handle': recipient.handle,
                'amount': str(amount),
                'currency': currency,
            },
        )

    notification = create_notification_record(
        recipient,
        'money_received',
        {
            'transaction_id': str(transaction_obj.id),
            'sender_handle': sender.handle,
            'amount': str(amount),
            'currency': currency,
            'note': note,
        },
    )

    try:
        from wallet.tasks import send_notification_task
        send_notification_task.delay(notification.id)
    except Exception:
        logger.exception('scheduled_transfer_notification_dispatch_failed')

    return transaction_obj


def calculate_next_execution(frequency, current_execution):
    if frequency == ScheduleFrequency.DAILY:
        return current_execution + timedelta(days=1)
    if frequency == ScheduleFrequency.WEEKLY:
        return current_execution + timedelta(weeks=1)
    if frequency == ScheduleFrequency.BIWEEKLY:
        return current_execution + timedelta(weeks=2)
    if frequency == ScheduleFrequency.MONTHLY:
        return current_execution + timedelta(days=30)
    if frequency == ScheduleFrequency.YEARLY:
        return current_execution + timedelta(days=365)
    return current_execution


def run_scheduled_transfers():
    """
    Process due scheduled transfers through execute_p2p_transfer.
    On failure (e.g. insufficient funds), notify sender and advance next_execution without retrying.
    """
    now = timezone.now()
    due_transfers = ScheduledTransfer.objects.filter(
        status=ScheduledTransferStatus.ACTIVE,
        next_execution__lte=now,
    ).select_related('sender', 'recipient', 'sender__wallet', 'recipient__wallet')

    processed_count = 0
    failed_count = 0
    skipped_count = 0
    failures = []

    for scheduled_transfer in due_transfers:
        try:
            with transaction.atomic():
                scheduled_transfer = ScheduledTransfer.objects.select_for_update().get(
                    id=scheduled_transfer.id
                )

                if scheduled_transfer.status != ScheduledTransferStatus.ACTIVE:
                    skipped_count += 1
                    continue
                if scheduled_transfer.next_execution > now:
                    skipped_count += 1
                    continue
                if scheduled_transfer.end_date and scheduled_transfer.end_date < now:
                    scheduled_transfer.status = ScheduledTransferStatus.COMPLETED
                    scheduled_transfer.save(update_fields=['status'])
                    skipped_count += 1
                    continue
                if (
                    scheduled_transfer.max_executions
                    and scheduled_transfer.total_executions >= scheduled_transfer.max_executions
                ):
                    scheduled_transfer.status = ScheduledTransferStatus.COMPLETED
                    scheduled_transfer.save(update_fields=['status'])
                    skipped_count += 1
                    continue

                idempotency_key = f'scheduled-{scheduled_transfer.id}-{scheduled_transfer.total_executions + 1}'
                note = (
                    f'Scheduled transfer: {scheduled_transfer.note}'
                    if scheduled_transfer.note
                    else 'Scheduled transfer'
                )

                try:
                    transaction_obj = execute_p2p_transfer(
                        sender=scheduled_transfer.sender,
                        recipient=scheduled_transfer.recipient,
                        amount=scheduled_transfer.amount,
                        currency=scheduled_transfer.currency,
                        note=note,
                        idempotency_key=idempotency_key,
                        skip_limit_checks=False,
                    )
                except TransferExecutionError as exc:
                    failed_count += 1
                    failures.append({
                        'scheduled_transfer_id': scheduled_transfer.id,
                        'reason': exc.reason,
                    })
                    logger.error(
                        'scheduled_transfer_failed',
                        extra={
                            'scheduled_transfer_id': scheduled_transfer.id,
                            'reason': exc.reason,
                        },
                    )
                    create_notification_record(
                        scheduled_transfer.sender,
                        'scheduled_transfer_failed',
                        {
                            'scheduled_transfer_id': scheduled_transfer.id,
                            'amount': str(scheduled_transfer.amount),
                            'currency': scheduled_transfer.currency,
                            'reason': exc.reason,
                        },
                    )
                    scheduled_transfer.last_execution = now
                    scheduled_transfer.next_execution = calculate_next_execution(
                        scheduled_transfer.frequency,
                        scheduled_transfer.next_execution,
                    )
                    scheduled_transfer.save(update_fields=['last_execution', 'next_execution'])
                    continue

                scheduled_transfer.last_execution = now
                scheduled_transfer.total_executions += 1
                scheduled_transfer.next_execution = calculate_next_execution(
                    scheduled_transfer.frequency,
                    scheduled_transfer.next_execution,
                )

                if scheduled_transfer.end_date and scheduled_transfer.next_execution > scheduled_transfer.end_date:
                    scheduled_transfer.status = ScheduledTransferStatus.COMPLETED
                elif (
                    scheduled_transfer.max_executions
                    and scheduled_transfer.total_executions >= scheduled_transfer.max_executions
                ):
                    scheduled_transfer.status = ScheduledTransferStatus.COMPLETED

                scheduled_transfer.save()

                AuditLog.objects.create(
                    user=scheduled_transfer.sender,
                    action='scheduled_transfer_executed',
                    metadata={
                        'scheduled_transfer_id': scheduled_transfer.id,
                        'transaction_id': str(transaction_obj.id),
                        'amount': str(scheduled_transfer.amount),
                        'currency': scheduled_transfer.currency,
                    },
                )

                processed_count += 1

        except Exception as exc:
            logger.exception(
                'scheduled_transfer_error',
                extra={'scheduled_transfer_id': scheduled_transfer.id},
            )
            failed_count += 1
            failures.append({
                'scheduled_transfer_id': scheduled_transfer.id,
                'reason': str(exc),
            })

    return {
        'processed_count': processed_count,
        'failed_count': failed_count,
        'skipped_count': skipped_count,
        'failures': failures,
    }
