import hashlib
import hmac
import json
import logging

import requests
from django.utils import timezone

from wallet.models import WebhookDelivery, WebhookDeliveryStatus

logger = logging.getLogger(__name__)

WEBHOOK_MAX_RETRIES = 5


def build_payment_intent_payload(intent, event_type):
    return {
        'event': event_type,
        'mode': intent.mode,
        'payment_intent': {
            'id': intent.id,
            'status': intent.status,
            'amount': str(intent.amount),
            'currency': intent.currency,
            'external_reference': intent.external_reference,
            'transaction_id': str(intent.resulting_transaction_id) if intent.resulting_transaction_id else None,
        },
    }


def sign_webhook_payload(payload_bytes, secret):
    return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def enqueue_payment_intent_webhook(intent, event_type):
    if not intent.merchant.webhook_url:
        return None

    payload = build_payment_intent_payload(intent, event_type)
    delivery = WebhookDelivery.objects.create(
        merchant=intent.merchant,
        payment_intent=intent,
        event_type=event_type,
        target_url=intent.merchant.webhook_url,
        payload=payload,
    )

    from wallet.tasks import deliver_webhook_task

    deliver_webhook_task.delay(delivery.id)
    return delivery


def deliver_webhook(delivery_id):
    delivery = WebhookDelivery.objects.select_related('merchant', 'payment_intent').get(pk=delivery_id)
    payload_bytes = json.dumps(delivery.payload, sort_keys=True, separators=(',', ':')).encode()
    signature = sign_webhook_payload(payload_bytes, delivery.merchant.webhook_secret)

    delivery.attempt_count += 1
    try:
        response = requests.post(
            delivery.target_url,
            data=payload_bytes,
            headers={
                'Content-Type': 'application/json',
                'X-Wallet-Signature': signature,
            },
            timeout=15,
        )
        delivery.status_code = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status = WebhookDeliveryStatus.DELIVERED
            delivery.delivered_at = timezone.now()
            delivery.save()
            return {'status': 'delivered', 'status_code': response.status_code}

        delivery.last_error = response.text[:1000]
        delivery.status = WebhookDeliveryStatus.FAILED if delivery.attempt_count >= WEBHOOK_MAX_RETRIES else WebhookDeliveryStatus.PENDING
        delivery.save()
        raise WebhookDeliveryError(f'HTTP {response.status_code}')
    except requests.RequestException as exc:
        delivery.last_error = str(exc)
        delivery.status = WebhookDeliveryStatus.FAILED if delivery.attempt_count >= WEBHOOK_MAX_RETRIES else WebhookDeliveryStatus.PENDING
        delivery.save()
        raise WebhookDeliveryError(str(exc)) from exc


class WebhookDeliveryError(Exception):
    pass
