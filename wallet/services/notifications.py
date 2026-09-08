import logging
import os

from wallet.models import Notification, PushDevice, User

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

    if notification.type.startswith(('transfer_', 'payment_request_', 'split_request_', 'wallet_')):
        _send_push(notification)

    logger.info(
        'notification_delivered',
        extra={
            'notification_id': notification_id,
            'user_id': notification.user_id,
            'type': notification.type,
        },
    )
    return {'status': 'delivered', 'notification_id': notification_id}


def _send_push(notification):
    """Send FCM push notifications when Firebase Admin is configured."""
    try:
        import firebase_admin
        from firebase_admin import messaging
    except ImportError:
        logger.warning('firebase_admin_not_installed')
        return

    try:
        firebase_admin.get_app()
    except ValueError:
        credential_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        if not credential_path:
            logger.warning('firebase_credentials_not_configured')
            return
        firebase_admin.initialize_app()

    devices = PushDevice.objects.filter(user=notification.user, active=True)
    if not devices.exists():
        return

    payload = notification.payload or {}
    message = messaging.MulticastMessage(
        tokens=list(devices.values_list('token', flat=True)),
        notification=messaging.Notification(
            title=payload.get('title', 'DSD PAY'),
            body=payload.get('message', 'You have a new wallet update.'),
        ),
        data={key: str(value) for key, value in payload.items() if value is not None},
    )
    response = messaging.send_each_for_multicast(message)
    for device, result in zip(devices, response.responses):
        if not result.success and 'registration-token-not-registered' in str(result.exception):
            device.active = False
            device.save(update_fields=['active'])


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
