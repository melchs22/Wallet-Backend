import logging

from wallet.models import Notification, User

logger = logging.getLogger(__name__)


def create_notification_record(user, notification_type, payload):
    """Create the notification row (synchronous, inside the caller's transaction)."""
    return Notification.objects.create(
        user=user,
        type=notification_type,
        payload=payload,
    )


def deliver_notification(notification_id):
    """
    Deliver a notification via external channels (push, email, SMS).
    Stub until delivery providers are integrated — the row already exists.
    """
    try:
        notification = Notification.objects.select_related('user').get(id=notification_id)
    except Notification.DoesNotExist:
        logger.warning('deliver_notification_missing', extra={'notification_id': notification_id})
        return {'status': 'not_found'}

    logger.info(
        'notification_delivered',
        extra={
            'notification_id': notification_id,
            'user_id': notification.user_id,
            'type': notification.type,
        },
    )
    return {'status': 'delivered', 'notification_id': notification_id}


def broadcast_notification(notification_type, payload, user_ids=None):
    """
    Bulk-create notifications for many users.
    Used by admin broadcast — must run off the request thread.
    """
    if user_ids is None:
        users = User.objects.filter(is_staff=False, is_active=True)
    else:
        users = User.objects.filter(id__in=user_ids, is_staff=False, is_active=True)

    notifications = [
        Notification(user=user, type=notification_type, payload=payload)
        for user in users.iterator(chunk_size=500)
    ]

    created = Notification.objects.bulk_create(notifications, batch_size=500)
    logger.info(
        'broadcast_notification_complete',
        extra={'type': notification_type, 'count': len(created)},
    )
    return {'created_count': len(created)}
