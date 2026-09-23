import logging
import json
import os
from pathlib import Path

from wallet.models import Notification, PushDevice, TransactionApproval, User

logger = logging.getLogger(__name__)


def _service_account_info(value):
    info = json.loads(value)
    if isinstance(info, str):
        info = json.loads(info)
    if not isinstance(info, dict):
        raise ValueError('Firebase service account must be a JSON object.')
    if isinstance(info.get('private_key'), str):
        info['private_key'] = info['private_key'].replace('\\n', '\n')
    return info


def create_notification_record(user, notification_type, payload):
    """Create the notification row (synchronous, inside the caller's transaction)."""
    payload = dict(payload or {})
    payload.setdefault('type', notification_type)
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
        'payment_sent': 'Payment sent',
        'payment_request_expired': 'Payment request expired',
        'device_signed_in_elsewhere': 'Security notice',
        'new_device_login': 'Approve new device sign-in',
        'device_revoked': 'Device signed out',
        'mobile_money_withdrawal': 'Transfer sent',
        'mobile_money_transaction_completed': 'Withdrawal completed',
        'mobile_money_transaction_failed': 'Withdrawal failed',
        'merchant_withdrawal_completed': 'Merchant withdrawal completed',
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
    if notification_type == 'payment_sent':
        return (
            f"You paid {amount} {currency} to {payload.get('recipient_display_name', 'the merchant')} "
            f"with a fee of {payload.get('fee_amount', '0.00')} {currency}. "
            f"Your balance is {payload.get('balance_after', '0.00')} {currency}."
        )
    if notification_type == 'device_signed_in_elsewhere':
        return f"A new device signed in to your wallet. Please verify your account if this was not you."
    if notification_type == 'new_device_login':
        return f"Approve sign-in from {payload.get('new_device_name', 'a new device')}."
    if notification_type == 'device_revoked':
        return 'This device was signed out remotely.'
    if notification_type == 'mobile_money_withdrawal':
        return (
            f"Your transfer of {amount} {currency} to "
            f"{payload.get('destination_phone', 'the recipient')} was sent."
        )
    if notification_type == 'mobile_money_transaction_completed':
        return f'Your withdrawal of {amount} {currency} was completed.'
    if notification_type == 'mobile_money_transaction_failed':
        return f'Your withdrawal of {amount} {currency} failed.'
    if notification_type == 'merchant_withdrawal_completed':
        return f'Your bank withdrawal of {amount} {currency} was completed.'
    if notification_type == 'parental_link_approved':
        return f"{payload.get('child_display_name', 'Your child')} approved the parental link."
    if notification_type == 'parental_link_declined':
        return f"{payload.get('child_display_name', 'The child')} declined the parental link."
    if notification_type == 'transfer_received':
        return f"You received {amount} {currency}."
    if notification_type == 'incoming_transfer':
        return f"{payload.get('sender_display_name', 'A user')} started a transfer of {amount} {currency}."
    return 'You have a new wallet update.'


def _localized_notification_content(notification_type, payload, language_code):
    """Return the notification-bar copy for the device's preferred language."""
    if language_code != 'fr':
        return (
            payload.get('title', 'DSD PAY'),
            payload.get('message', _notification_message(notification_type, payload)),
        )

    amount = payload.get('amount')
    currency = payload.get('currency', '')
    sender = payload.get('sender_display_name', 'Un utilisateur')
    if notification_type == 'transfer_approval_requested':
        return ('Approbation de transfert requise', f'{sender} veut envoyer {amount} {currency}.')
    if notification_type == 'payment_request_received':
        return ('Demande de paiement reçue', f'{payload.get("requester_display_name", "Un utilisateur")} demande {amount} {currency}.')
    if notification_type == 'split_request_received':
        return ('Paiement partagé demandé', f'Une demande de paiement de {amount} {currency} attend votre approbation.')
    if notification_type == 'parental_link_requested':
        return ('Approbation parentale requise', f'{payload.get("parent_display_name", "Un parent")} veut associer votre compte.')
    if notification_type in ('money_received', 'qr_payment_received', 'transfer_received'):
        return ('Argent reçu', f'Vous avez reçu {amount} {currency}.')
    if notification_type == 'incoming_transfer':
        return ('Transfert entrant', f'{sender} a commencé un transfert de {amount} {currency}.')
    if notification_type == 'payment_request_declined':
        return ('Demande refusée', f'{payload.get("payer_display_name", "Le payeur")} a refusé votre demande de {amount} {currency}.')
    if notification_type == 'payment_request_expired':
        return ('Demande expirée', f'Votre demande de {amount} {currency} a expiré.')
    if notification_type == 'payment_request_paid':
        return ('Demande payée', f'Votre demande de {amount} {currency} a été payée.')
    if notification_type == 'payment_sent':
        return (
            'Paiement envoyé',
            f'Vous avez payé {amount} {currency} à {payload.get("recipient_display_name", "le commerçant")}, '
            f'avec des frais de {payload.get("fee_amount", "0.00")} {currency}. '
            f'Solde : {payload.get("balance_after", "0.00")} {currency}.',
        )
    if notification_type == 'new_device_login':
        return ('Nouveau appareil', f'Approuvez la connexion depuis {payload.get("new_device_name", "un nouvel appareil")}.')
    if notification_type == 'device_signed_in_elsewhere':
        return ('Alerte de sécurité', 'Un nouvel appareil s’est connecté à votre portefeuille.')
    if notification_type == 'device_revoked':
        return ('Appareil déconnecté', 'Cet appareil a été déconnecté à distance.')
    if notification_type == 'mobile_money_withdrawal':
        return ('Transfert envoyé', f'Votre transfert de {amount} {currency} vers {payload.get("destination_phone", "le destinataire")} a été envoyé.')
    if notification_type == 'mobile_money_transaction_completed':
        return ('Retrait terminé', f'Votre retrait de {amount} {currency} est terminé.')
    if notification_type == 'mobile_money_transaction_failed':
        return ('Échec du retrait', f'Votre retrait de {amount} {currency} a échoué.')
    if notification_type == 'merchant_withdrawal_completed':
        return ('Retrait bancaire terminé', f'Votre retrait bancaire de {amount} {currency} est terminé.')
    if notification_type == 'parental_link_approved':
        return ('Lien parental approuvé', f'{payload.get("child_display_name", "Votre enfant")} a approuvé le lien parental.')
    if notification_type == 'parental_link_declined':
        return ('Lien parental refusé', f'{payload.get("child_display_name", "L’enfant")} a refusé le lien parental.')
    if notification_type == 'parental_link_approved':
        return ('Lien parental approuvé', f'{payload.get("child_display_name", "Votre enfant")} a approuvé le lien parental.')
    return ('DSD PAY', 'Vous avez une nouvelle mise à jour de votre portefeuille.')


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
        'wallet_', 'money_', 'qr_payment_', 'mobile_money_', 'incoming_transfer', 'device_signed_in_elsewhere', 'new_device_login'
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
                credential = credentials.Certificate(_service_account_info(credential_json))
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.error('firebase_credentials_invalid')
                return
        else:
            credential_candidates = [
                Path(os.getenv('FIREBASE_SERVICE_ACCOUNT_FILE', '')),
                Path('/opt/wallet-backend/secrets/firebase-service-account.json'),
                Path(__file__).resolve().parents[2] / 'dsd-wallet-firebase-adminsdk-fbsvc-457d21a5b0.json',
            ]
            local_credential_path = next(
                (path for path in credential_candidates if str(path) != '.' and path.exists()),
                None,
            )
            if local_credential_path is None:
                logger.warning('firebase_credentials_not_configured')
                return
            try:
                credential = credentials.Certificate(_service_account_info(local_credential_path.read_text()))
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                logger.error('firebase_local_credentials_invalid', extra={'path': str(local_credential_path)})
                return
        try:
            firebase_admin.initialize_app(credential)
        except ValueError:
            logger.error('firebase_initialization_failed')
            return

    payload = notification.payload or {}
    devices = PushDevice.objects.filter(user=notification.user, active=True)
    if notification.type == 'new_device_login':
        from wallet.models import TrustedDevice
        trusted_ids = TrustedDevice.objects.filter(
            user=notification.user,
            is_trusted=True,
            revoked_at__isnull=True,
        ).values_list('device_id', flat=True)
        devices = devices.filter(device_id__in=trusted_ids)
    target_device_id = payload.get('target_device_id')
    if target_device_id:
        devices = devices.filter(device_id=target_device_id)
    if not devices.exists():
        logger.warning(
            'notification_no_active_devices',
            extra={'notification_id': notification.id, 'user_id': notification.user_id},
        )
        return
    data = {key: str(value) for key, value in payload.items() if value is not None}
    devices_by_language = {}
    for device in devices:
        language = (device.language_code or 'fr').split('-', 1)[0].lower()
        devices_by_language.setdefault(language, []).append(device)

    for language, language_devices in devices_by_language.items():
        title, body = _localized_notification_content(notification.type, payload, language)
        message = messaging.MulticastMessage(
            tokens=[device.token for device in language_devices],
            notification=messaging.Notification(title=title, body=body),
            data=data,
            apns=messaging.APNSConfig(
                headers={'apns-push-type': 'alert', 'apns-priority': '10'},
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound='default', badge=1),
                ),
            ),
        )
        try:
            response = messaging.send_each_for_multicast(message)
        except Exception:
            logger.exception(
                'firebase_multicast_send_failed',
                extra={
                    'notification_id': notification.id,
                    'user_id': notification.user_id,
                    'platforms': [device.platform for device in language_devices],
                },
            )
            continue
        logger.info(
            'firebase_multicast_send_complete',
            extra={
                'notification_id': notification.id,
                'user_id': notification.user_id,
                'language': language,
                'success_count': response.success_count,
                'failure_count': response.failure_count,
            },
        )
        for device, result in zip(language_devices, response.responses):
            if not result.success and (
                'registration-token-not-registered' in str(result.exception)
                or 'not a valid FCM registration token' in str(result.exception)
            ):
                device.active = False
                device.save(update_fields=['active'])
            elif not result.success:
                logger.warning(
                    'firebase_device_send_failed',
                    extra={
                        'notification_id': notification.id,
                        'device_id': device.id,
                        'platform': device.platform,
                        'error': str(result.exception),
                    },
                )


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
