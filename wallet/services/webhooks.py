import hashlib
import hmac
import json
import logging

import requests
from django.utils import timezone

from wallet.models import WebhookDelivery, WebhookDeliveryStatus, TransactionApproval

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


def build_transaction_approval_payload(approval, event_type):
    """Build webhook payload for transaction approval events."""
    payload = {
        'event': event_type,
        'approval': {
            'id': approval.id,
            'approval_type': approval.approval_type,
            'status': approval.status,
            'amount': str(approval.amount),
            'currency': approval.currency,
            'note': approval.note,
            'expires_at': approval.expires_at.isoformat() if approval.expires_at else None,
        },
        'requester': {
            'id': str(approval.requester.id),
            'handle': approval.requester.handle,
            'display_name': approval.requester.display_name,
            'primary_phone_number': approval.requester.primary_phone_number,
        },
        'approver': {
            'id': str(approval.approver.id),
            'handle': approval.approver.handle,
            'display_name': approval.approver.display_name,
            'primary_phone_number': approval.approver.primary_phone_number,
        },
    }
    
    if approval.transaction:
        payload['approval']['transaction_id'] = str(approval.transaction.id)
    if approval.payment_request:
        payload['approval']['payment_request_id'] = approval.payment_request.id
    if approval.split_request:
        payload['approval']['split_request_id'] = approval.split_request.id
    
    return payload


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


def enqueue_transaction_approval_webhook(approval, event_type, webhook_url=None, webhook_secret=None):
    """Enqueue webhook delivery for transaction approval events."""
    if not webhook_url:
        # Try to get webhook URL from approver's settings if they have merchant account
        if hasattr(approval.approver, 'merchant_account') and approval.approver.merchant_account.webhook_url:
            webhook_url = approval.approver.merchant_account.webhook_url
            webhook_secret = approval.approver.merchant_account.webhook_secret
        else:
            return None
    
    payload = build_transaction_approval_payload(approval, event_type)
    
    # Create a simple webhook delivery record (reusing existing model for simplicity)
    # Note: This requires the approver to have a merchant account for webhooks
    if hasattr(approval.approver, 'merchant_account'):
        delivery = WebhookDelivery.objects.create(
            merchant=approval.approver.merchant_account,
            payment_intent=None,  # No payment intent for transaction approvals
            event_type=event_type,
            target_url=webhook_url,
            payload=payload,
        )
        
        from wallet.tasks import deliver_webhook_task
        deliver_webhook_task.delay(delivery.id)
        return delivery
    
    return None


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


def create_transaction_approval(transaction, approver, requester, approval_type, amount, currency, note=''):
    """Create a transaction approval request and send webhook notification."""
    approval = TransactionApproval.objects.create(
        transaction=transaction,
        approver=approver,
        requester=requester,
        approval_type=approval_type,
        amount=amount,
        currency=currency,
        note=note,
        status=TransactionApproval.ApprovalStatus.PENDING
    )
    
    # Send webhook notification for the approval request
    enqueue_transaction_approval_webhook(approval, 'approval_requested')
    
    return approval


def create_payment_request_approval(payment_request, approval_type='payment_request'):
    """Create an approval request for a payment request."""
    approval = TransactionApproval.objects.create(
        payment_request=payment_request,
        approver=payment_request.payer,
        requester=payment_request.requester,
        approval_type=approval_type,
        amount=payment_request.amount,
        currency=payment_request.currency,
        note=payment_request.note,
        status=TransactionApproval.ApprovalStatus.PENDING
    )
    
    # Send webhook notification
    enqueue_transaction_approval_webhook(approval, 'payment_request_created')
    
    return approval


def create_split_approval(split_request, participant, approval_type='split_bill'):
    """Create an approval request for a split bill participant."""
    approval = TransactionApproval.objects.create(
        split_request=split_request,
        approver=participant.payment_request.payer,
        requester=split_request.creator,
        approval_type=approval_type,
        amount=participant.amount_owed,
        currency=split_request.currency,
        note=f"Split payment: {split_request.note}" if split_request.note else "Split payment",
        status=TransactionApproval.ApprovalStatus.PENDING
    )
    
    # Send webhook notification
    enqueue_transaction_approval_webhook(approval, 'split_request_created')
    
    return approval
