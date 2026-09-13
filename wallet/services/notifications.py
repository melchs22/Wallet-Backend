import logging
import json
import os
from pathlib import Path

from wallet.models import Notification, PushDevice, TransactionApproval, User

logger = logging.getLogger(__name__)


def create_notification_record(user, notification_type, payload):
    """Create the notification row (synchronous, inside the caller's transaction)."""
    payload = dict(payload or {})
    payload.setdefault('title', {
        'transfer_approval_requested': 'Transfer approval required',
        'payment_request_received': 'Payment request received',
        'split_request_received': 'Split payment requested',
        'parental_link_requested': 'Parental link approval required',
        'money_received': 'Money received',
        'qr_payment_received': 'QR payment received',
        'payment_request_declined': 'Payment request declined',
        'parental_link_approved': 'Parental link approved',
        'parental_link_declined': 'Parental link declined',
            'transfer_received': 'Money received',
            'incoming_transfer': 'Incoming transfer',
        'payment_request_paid': 'Payment request paid',
        'payment_request_expired': 'Payment request expired',
        'device_signed_in_elsewhere': 'Security notice',
    }.get(notification_type, 'DSD PAY'))
    payload.setdefault('message', _notification_message(notification_type, payload))
    return Notification.objects.create(
        user=user,
        type=notification_type,
        payload=payload,
    )


def _notification_message(notification_type, payload):
    amount = payload.get('amount')
    currency = payload.get('currency', '')
    if notification_type == 'transfer_approval_requested':
        return f"{payload.get('sender_display_name', 'A user')} wants to send {amount} {currency}."
    if notification_type == 'payment_request_received':
        return f"{payload.get('requester_display_name', 'A user')} requested {amount} {currency}."
    if notification_type == 'split_request_received':
        return f"A split payment request for {amount} {currency} needs your approval."
    if notification_type == 'parental_link_requested':
        return f"{payload.get('parent_display_name', 'A parent')} wants to link your account."
    if notification_type in ('money_received', 'qr_payment_received'):
        return f"You received {amount} {currency}."
    if notification_type == 'payment_request_declined':
        return f"{payload.get('payer_display_name', 'The payer')} declined your request for {amount} {currency}."
    if notification_type == 'payment_request_expired':
        return f"Your request for {amount} {currency} expired. Send a new request if you still need payment."
    if notification_type == 'device_signed_in_elsewhere':
        return f"A new device signed in to your wallet. Please verify your account if this was not you."
    if notification_type == 'parental_link_approved':
        return f"{payload.get('child_display_name', 'Your child')} approved the parental link."
    if notification_type == 'parental_link_declined':
        return f"{payload.get('child_display_name', 'The child')} declined the parental link."
    if notification_type == 'transfer_received':
        return f"You received {amount} {currency}."
    if notification_type == 'incoming_transfer':
        return f"{payload.get('sender_display_name', 'A user')} started a transfer of {amount} {currency}."
    return 'You have a new wallet update.'


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

    if notification.type.startswith((
        'transfer_', 'payment_request_', 'split_request_', 'parental_',
        'wallet_', 'money_', 'qr_payment_', 'mobile_money_', 'incoming_transfer', 'device_signed_in_elsewhere'
    )):
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


def remove_expired_approval_notifications(user=None):
    """Remove unread approval prompts that can no longer be acted on."""
    expired_ids = list(TransactionApproval.objects.filter(
        status__in=[
            TransactionApproval.ApprovalStatus.EXPIRED,
            TransactionApproval.ApprovalStatus.APPROVED,
            TransactionApproval.ApprovalStatus.DECLINED,
        ],
    ).values_list('id', flat=True))
    notifications = Notification.objects.filter(
        type__in=['transfer_approval_requested', 'payment_request_received', 'split_request_received'],
        read_at__isnull=True,
        payload__approval_id__in=expired_ids,
    )
    if user is not None:
        notifications = notifications.filter(user=user)
    return notifications.delete()[0]


def _send_push(notification):
    """Send FCM push notifications when Firebase Admin is configured."""
    try:
        import firebase_admin
        from firebase_admin import credentials
        from firebase_admin import messaging
    except ImportError:
        logger.warning('firebase_admin_not_installed')
        return

    try:
        firebase_admin.get_app()
    except ValueError:
        credential_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
        if credential_json:
            try:
                credential = credentials.Certificate(json.loads(credential_json))
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.exception('firebase_credentials_invalid_json')
                return
        else:
            local_credential_path = Path(__file__).resolve().parents[2] / 'dsd-wallet-firebase-adminsdk-fbsvc-457d21a5b0.json'
            if not local_credential_path.exists():
                logger.warning('firebase_credentials_not_configured')
                return
            credential = credentials.Certificate(str(local_credential_path))
        firebase_admin.initialize_app(credential)

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
        apns=messaging.APNSConfig(
            headers={'apns-push-type': 'alert', 'apns-priority': '10'},
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound='default', badge=1),
            ),
        ),
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
