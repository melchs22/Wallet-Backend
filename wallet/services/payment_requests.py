import logging

from django.db import transaction
from django.utils import timezone

from wallet.models import PaymentRequest, PaymentRequestStatus

logger = logging.getLogger(__name__)


def expire_payment_requests():
    """
    Mark pending payment requests past expires_at as expired.
    Split participant statuses derive from their linked payment request.
    """
    now = timezone.now()

    with transaction.atomic():
        expired_qs = PaymentRequest.objects.filter(
            status=PaymentRequestStatus.PENDING,
            expires_at__lt=now,
        )
        expired_ids = list(expired_qs.values_list('id', flat=True))
        count = expired_qs.update(status=PaymentRequestStatus.EXPIRED)

    if count:
        logger.info(
            'expire_payment_requests_complete',
            extra={'expired_count': count, 'payment_request_ids': expired_ids},
        )

    return {'expired_count': count, 'payment_request_ids': expired_ids}
