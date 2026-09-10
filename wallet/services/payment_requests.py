import logging

from django.db import transaction
from django.utils import timezone

from wallet.models import PaymentRequest, PaymentRequestStatus
from wallet.services.notifications import create_notification_record, deliver_notification

logger = logging.getLogger(__name__)


def expire_payment_requests():
    """
    Mark pending payment requests past expires_at as expired.
    Split participant statuses derive from their linked payment request.
    """
    now = timezone.now()

    expired_notification_ids = []
    with transaction.atomic():
        expired_qs = PaymentRequest.objects.filter(
            status=PaymentRequestStatus.PENDING,
            expires_at__lt=now,
        )
        expired_requests = list(expired_qs.select_related('requester', 'payer'))
        expired_ids = [payment_request.id for payment_request in expired_requests]
        count = expired_qs.update(status=PaymentRequestStatus.EXPIRED)

        for payment_request in expired_requests:
            notification = create_notification_record(
                payment_request.requester,
                'payment_request_expired',
                {
                    'amount': str(payment_request.amount),
                    'currency': payment_request.currency,
                    'payment_request_id': payment_request.id,
                    'payer_handle': payment_request.payer.handle if payment_request.payer else '',
                },
            )
            expired_notification_ids.append(notification.id)

    for notification_id in expired_notification_ids:
        deliver_notification(notification_id)

    if count:
        logger.info(
            'expire_payment_requests_complete',
            extra={'expired_count': count, 'payment_request_ids': expired_ids},
        )

    return {'expired_count': count, 'payment_request_ids': expired_ids}
