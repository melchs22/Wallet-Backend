import logging
from datetime import timedelta

from django.utils import timezone

from wallet.models import Notification, ProcessedRequest, TransferAttempt

logger = logging.getLogger(__name__)

PROCESSED_REQUEST_RETENTION_DAYS = 90
NOTIFICATION_RETENTION_DAYS = 60
TRANSFER_ATTEMPT_RETENTION_DAYS = 365


def cleanup_processed_requests(retention_days=PROCESSED_REQUEST_RETENTION_DAYS):
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = ProcessedRequest.objects.filter(created_at__lt=cutoff).delete()
    logger.info('cleanup_processed_requests', extra={'deleted': deleted, 'retention_days': retention_days})
    return {'deleted': deleted}


def cleanup_notifications(retention_days=NOTIFICATION_RETENTION_DAYS):
    """Delete read notifications older than the retention window. Never touch unread."""
    cutoff = timezone.now() - timedelta(days=retention_days)
    deleted, _ = Notification.objects.filter(
        read_at__isnull=False,
        read_at__lt=cutoff,
    ).delete()
    logger.info('cleanup_notifications', extra={'deleted': deleted, 'retention_days': retention_days})
    return {'deleted': deleted}


def archive_transfer_attempts(retention_days=TRANSFER_ATTEMPT_RETENTION_DAYS):
    """
    Delete transfer attempt rows older than retention.
    Aggregate counts for fraud dashboard should be computed before deletion in a future iteration.
    """
    cutoff = timezone.now() - timedelta(days=retention_days)
    total_before = TransferAttempt.objects.filter(created_at__lt=cutoff).count()
    deleted, _ = TransferAttempt.objects.filter(created_at__lt=cutoff).delete()
    logger.info(
        'archive_transfer_attempts',
        extra={'deleted': deleted, 'retention_days': retention_days, 'total_before': total_before},
    )
    return {'deleted': deleted, 'total_before': total_before}
