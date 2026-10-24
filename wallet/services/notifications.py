import logging
import json
import os
from pathlib import Path

from wallet.models import Notification, PushDevice, TransactionApproval, User

logger = logging.getLogger(__name__)

_NOTIFICATION_COPY = {
    'transfer_approval_requested': (
        'Transfer approval required',
        '{sender} wants to send {amount} {currency}.',
        'Approbation de transfert requise',
        '{sender} souhaite vous envoyer {amount} {currency}.',
    ),
    'payment_request_received': (
        'Payment request received',
        '{requester} requested {amount} {currency}.',
        'Demande de paiement reçue',
        '{requester} vous demande {amount} {currency}.',
    ),
    'split_request_received': (
        'Split payment requested',
        '{creator} requested {amount} {currency} as your share of a split payment.',
        'Paiement partagé demandé',
        '{creator} vous demande {amount} {currency} pour votre part du paiement partagé.',
    ),
    'parental_link_requested': (
        'Parental link approval required',
        '{parent} wants to link your account.',
        'Approbation du lien parental requise',
        '{parent} souhaite associer votre compte au sien.',
    ),
    'money_received': (
        'Money received',
        'You received {amount} {currency}.',
        'Argent reçu',
        'Vous avez reçu {amount} {currency}.',
    ),
    'qr_payment_received': (
        'QR payment received',
        'You received {amount} {currency} by QR payment.',
        'Paiement QR reçu',
        'Vous avez reçu {amount} {currency} par paiement QR.',
    ),
    'transfer_received': (
        'Money received',
        'You received {amount} {currency} from {sender}.',
        'Argent reçu',
        'Vous avez reçu {amount} {currency} de la part de {sender}.',
    ),
    'incoming_transfer': (
        'Incoming transfer',
        '{sender} started a transfer of {amount} {currency}.',
        'Transfert entrant',
        '{sender} a commencé un transfert de {amount} {currency}.',
    ),
    'incoming_qr_payment': (
        'QR payment pending',
        '{payer} is preparing a QR payment of {amount} {currency}.',
        'Paiement QR en attente',
        '{payer} prépare un paiement QR de {amount} {currency}.',
    ),
    'payment_request_declined': (
        'Payment request declined',
        '{payer} declined your request for {amount} {currency}.',
        'Demande de paiement refusée',
        '{payer} a refusé votre demande de {amount} {currency}.',
    ),
    'payment_request_expired': (
        'Payment request expired',
        'Your request for {amount} {currency} has expired.',
        'Demande de paiement expirée',
        'Votre demande de {amount} {currency} a expiré.',
    ),
    'payment_request_paid': (
        'Payment request paid',
        '{payer} paid your request for {amount} {currency}.',
        'Demande de paiement réglée',
        '{payer} a réglé votre demande de {amount} {currency}.',
    ),
    'payment_request_cancelled': (
        'Payment request cancelled',
        'A payment request from {requester} has been cancelled.',
        'Demande de paiement annulée',
        'Une demande de paiement de {requester} a été annulée.',
    ),
    'payment_sent': (
        'Payment sent',
        'You paid {amount} {currency} to {recipient} with a fee of {fee_amount} {currency}. '
        'Your balance is {balance_after} {currency}.',
        'Paiement envoyé',
        'Vous avez payé {amount} {currency} à {recipient}, avec des frais de {fee_amount} {currency}. '
        'Votre solde est de {balance_after} {currency}.',
    ),
    'transaction_reversed': (
        'Transaction reversed',
        '{message}',
        'Transaction annulée',
        '{message_fr}',
    ),
    'utility_payment_completed': (
        'Utility payment completed',
        'Your {service} payment of {amount} {currency} was completed.',
        'Paiement de facture terminé',
        'Votre paiement {service} de {amount} {currency} a été effectué.',
    ),
    'device_signed_in_elsewhere': (
        'Security notice',
        'A new device signed in to your wallet. If this was not you, review your security settings.',
        'Alerte de sécurité',
        'Un nouvel appareil s’est connecté à votre portefeuille. Si ce n’était pas vous, vérifiez vos paramètres de sécurité.',
    ),
    'new_device_login': (
        'Approve new device sign-in',
        'Approve sign-in from {device}.',
        'Connexion sur un nouvel appareil',
        'Approuvez la connexion depuis {device}.',
    ),
    'device_revoked': (
        'Device signed out',
        'This device was signed out remotely.',
        'Appareil déconnecté',
        'Cet appareil a été déconnecté à distance.',
    ),
    'mobile_money_withdrawal': (
        'Transfer submitted',
        'Your transfer of {amount} {currency} to {destination} was submitted.',
        'Transfert soumis',
        'Votre transfert de {amount} {currency} vers {destination} a été soumis.',
    ),
    'mobile_money_transaction_completed': (
        'Mobile money transaction completed',
        'Your mobile money transaction of {amount} {currency} was completed.',
        'Opération mobile money terminée',
        'Votre opération mobile money de {amount} {currency} est terminée.',
    ),
    'mobile_money_transaction_failed': (
        'Mobile money transaction failed',
        'Your mobile money transaction of {amount} {currency} could not be completed.',
        'Échec de l’opération mobile money',
        'Votre opération mobile money de {amount} {currency} n’a pas pu être effectuée.',
    ),
    'merchant_withdrawal_completed': (
        'Merchant withdrawal completed',
        'Your bank withdrawal of {amount} {currency} was completed.',
        'Retrait bancaire du commerçant terminé',
        'Votre retrait bancaire de {amount} {currency} est terminé.',
    ),
    'merchant_payment_received': (
        'Merchant payment received',
        'You received a payment of {amount} {currency} from {payer}.',
        'Paiement commerçant reçu',
        'Vous avez reçu un paiement de {amount} {currency} de la part de {payer}.',
    ),
    'scheduled_transfer_failed': (
        'Scheduled transfer failed',
        'Your scheduled transfer of {amount} {currency} could not be completed. Check your balance and try again.',
        'Échec du transfert programmé',
        'Votre transfert programmé de {amount} {currency} n’a pas pu être effectué. Vérifiez votre solde et réessayez.',
    ),
    'parental_link_approved': (
        'Parental link approved',
        '{child} approved the parental link.',
        'Lien parental approuvé',
        '{child} a approuvé le lien parental.',
    ),
    'parental_link_declined': (
        'Parental link declined',
        '{child} declined the parental link.',
        'Lien parental refusé',
        '{child} a refusé le lien parental.',
    ),
    'wallet_topup': (
        'Wallet credited',
        'Your wallet was credited with {amount} {currency}.',
        'Portefeuille crédité',
        'Votre portefeuille a été crédité de {amount} {currency}.',
    ),
    'dispute_resolved': (
        'Dispute resolved',
        'Your dispute was {resolution}. Open the dispute for details.',
        'Litige résolu',
        'Votre litige a été {resolution}. Ouvrez le litige pour consulter les détails.',
    ),
    'merchant_account_approved': (
        'Merchant account approved',
        '{business} is approved and ready to use.',
        'Compte commerçant approuvé',
        '{business} est approuvé et prêt à être utilisé.',
    ),
    'merchant_account_rejected': (
        'Merchant account update',
        'The application for {business} was not approved. Review the application for details.',
        'Mise à jour du compte commerçant',
        'La demande pour {business} n’a pas été approuvée. Consultez-la pour plus de détails.',
    ),
}


def _notification_values(payload, language):
    def value(*keys, default=''):
        for key in keys:
            item = payload.get(key)
            if item not in (None, ''):
                return str(item)
        return default

    resolution = value('resolution')
    resolution_map = {
        'reverse': ('reversed', 'annulé'),
        'deny': ('denied', 'refusé'),
    }
    resolution_text = resolution_map.get(resolution, ('updated', 'mis à jour'))
    return {
        'amount': value('amount', default='the requested amount' if language == 'en' else 'le montant demandé'),
        'currency': value('currency'),
        'sender': value('sender_display_name', 'sender_handle', default='A user' if language == 'en' else 'Un utilisateur'),
        'requester': value('requester_display_name', 'requester_handle', default='A user' if language == 'en' else 'Un utilisateur'),
        'creator': value('creator_display_name', 'creator_handle', default='A user' if language == 'en' else 'Un utilisateur'),
        'payer': value('payer_display_name', 'payer_handle', default='The payer' if language == 'en' else 'Le payeur'),
        'parent': value('parent_display_name', 'parent_handle', default='A parent' if language == 'en' else 'Un parent'),
        'child': value('child_display_name', default='The child' if language == 'en' else 'L’enfant'),
        'recipient': value('recipient_display_name', 'recipient_handle', default='the recipient' if language == 'en' else 'le destinataire'),
        'fee_amount': value('fee_amount', default='0.00'),
        'balance_after': value('balance_after', default='0.00'),
        'device': value('new_device_name', default='a new device' if language == 'en' else 'un nouvel appareil'),
        'destination': value('destination_phone', default='the recipient' if language == 'en' else 'le destinataire'),
        'message': value('message_en', 'message', default='You have a new wallet notification.'),
        'message_fr': value('message_fr', default='Vous avez une nouvelle notification de votre portefeuille.'),
        'service': value('service', default='utility' if language == 'en' else 'service'),
        'business': value('business_name', default='Your business' if language == 'en' else 'Votre entreprise'),
        'resolution': resolution_text[1] if language == 'fr' else resolution_text[0],
    }


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
    title, message = _localized_notification_content(notification_type, payload, 'en')
    payload.setdefault('title', title)
    payload.setdefault('message', message)
    return Notification.objects.create(
        user=user,
        type=notification_type,
        payload=payload,
    )


def _notification_message(notification_type, payload):
    copy = _NOTIFICATION_COPY.get(notification_type)
    if copy:
        return copy[1].format_map(_notification_values(payload, 'en'))
    return payload.get('message_en', payload.get('message', 'You have a new wallet notification.'))


def _localized_notification_content(notification_type, payload, language_code):
    """Return notification copy in English or French."""
    language = (language_code or 'en').split('-', 1)[0].lower()
    copy = _NOTIFICATION_COPY.get(notification_type)
    if copy:
        title_en, message_en, title_fr, message_fr = copy
        values = _notification_values(payload, language)
        return (
            title_fr if language == 'fr' else title_en,
            (message_fr if language == 'fr' else message_en).format_map(values),
        )

    if language == 'fr':
        return (
            payload.get('title_fr') or 'DSD PAY',
            payload.get('message_fr') or 'Vous avez une nouvelle notification de votre portefeuille.',
        )
    return (
        payload.get('title_en') or payload.get('title') or 'DSD PAY',
        payload.get('message_en') or payload.get('message') or 'You have a new wallet notification.',
    )


def localized_notification_payload(notification, language_code):
    payload = dict(notification.payload or {})
    title, message = _localized_notification_content(
        notification.type,
        payload,
        'fr' if (language_code or '').split('-', 1)[0].lower() == 'fr' else 'en',
    )
    payload.update({'title': title, 'message': message})
    return payload


def should_send_notification_push(notification_type):
    return notification_type.startswith((
        'transfer_', 'payment_request_', 'split_request_', 'parental_',
        'wallet_', 'money_', 'qr_payment_', 'mobile_money_', 'transaction_',
    )) or notification_type in {
        'incoming_transfer',
        'incoming_qr_payment',
        'payment_sent',
        'merchant_payment_received',
        'merchant_withdrawal_completed',
        'merchant_account_approved',
        'merchant_account_rejected',
        'scheduled_transfer_failed',
        'utility_payment_completed',
        'dispute_resolved',
        'device_signed_in_elsewhere',
        'device_revoked',
        'new_device_login',
    }


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

    if should_send_notification_push(notification.type):
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
    unique_devices = {}
    for device in devices.order_by('-last_seen_at'):
        identity = device.device_id or device.token
        unique_devices.setdefault(identity, device)
    devices = list(unique_devices.values())
    if not devices:
        logger.warning(
            'notification_no_active_devices',
            extra={'notification_id': notification.id, 'user_id': notification.user_id},
        )
        return
    language = (notification.user.language_code or 'en').split('-', 1)[0].lower()
    language = 'fr' if language == 'fr' else 'en'
    title, body = _localized_notification_content(notification.type, payload, language)
    data = {key: str(value) for key, value in payload.items() if value is not None}
    data.update({
        'type': notification.type,
        'title': title,
        'message': body,
    })
    data['notification_id'] = str(notification.id)
    message = messaging.MulticastMessage(
        tokens=[device.token for device in devices],
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
                'platforms': [device.platform for device in devices],
            },
        )
        return
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
    for device, result in zip(devices, response.responses):
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
