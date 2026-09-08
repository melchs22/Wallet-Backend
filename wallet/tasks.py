import json
import logging

from celery import shared_task
from django.core.management import call_command

from wallet.services.cleanup import (
    archive_transfer_attempts,
    cleanup_notifications,
    cleanup_processed_requests,
)
from wallet.services.mobile_money import process_mobile_money_webhook_event
from wallet.services.notifications import broadcast_notification, deliver_notification
from wallet.services.payment_requests import expire_payment_requests
from wallet.services.reconciliation import reconcile_balances
from wallet.services.transfers import run_scheduled_transfers
from wallet.services.exchange_rates import refresh_exchange_rates
from wallet.services.webhooks import deliver_webhook
from wallet.models import Merchant, MerchantApiKey, MerchantMode
import hashlib
import secrets

logger = logging.getLogger(__name__)


def _log_task_start(task_name, **kwargs):
    logger.info(json.dumps({'event': 'task_started', 'task': task_name, **kwargs}))


def _log_task_success(task_name, result):
    logger.info(json.dumps({'event': 'task_succeeded', 'task': task_name, 'result': result}))


def _log_task_failure(task_name, error):
    logger.error(json.dumps({'event': 'task_failed', 'task': task_name, 'error': str(error)}))


@shared_task(name='wallet.tasks.health_check_task', ignore_result=True)
def health_check_task():
    """Trivial task to verify Celery pipeline end-to-end."""
    _log_task_start('health_check_task')
    _log_task_success('health_check_task', {'status': 'ok'})
    return {'status': 'ok'}


@shared_task(
    name='wallet.tasks.reconcile_balances_task',
    bind=True,
    max_retries=2,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def reconcile_balances_task(self, fix=False):
    _log_task_start('reconcile_balances_task', fix=fix)
    try:
        result = reconcile_balances(fix=fix)
        _log_task_success('reconcile_balances_task', result)
        if result.get('drift_count', 0) > 0:
            logger.error(
                json.dumps({'event': 'reconcile_balances_drift_alert', **result})
            )
        return result
    except Exception as exc:
        _log_task_failure('reconcile_balances_task', exc)
        raise self.retry(exc=exc)


@shared_task(name='wallet.tasks.expire_payment_requests_task', ignore_result=True)
def expire_payment_requests_task():
    _log_task_start('expire_payment_requests_task')
    result = expire_payment_requests()
    _log_task_success('expire_payment_requests_task', result)
    return result


@shared_task(
    name='wallet.tasks.run_scheduled_transfers_task',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def run_scheduled_transfers_task(self):
    _log_task_start('run_scheduled_transfers_task')
    try:
        result = run_scheduled_transfers()
        _log_task_success('run_scheduled_transfers_task', result)
        if result.get('failed_count', 0) > 0:
            logger.error(
                json.dumps({'event': 'scheduled_transfers_failures', **result})
            )
        return result
    except Exception as exc:
        _log_task_failure('run_scheduled_transfers_task', exc)
        raise self.retry(exc=exc)


@shared_task(name='wallet.tasks.clear_expired_sessions_task', ignore_result=True)
def clear_expired_sessions_task():
    _log_task_start('clear_expired_sessions_task')
    call_command('clearsessions', verbosity=0)
    _log_task_success('clear_expired_sessions_task', {'status': 'ok'})
    return {'status': 'ok'}


@shared_task(name='wallet.tasks.cleanup_processed_requests_task', ignore_result=True)
def cleanup_processed_requests_task():
    _log_task_start('cleanup_processed_requests_task')
    result = cleanup_processed_requests()
    _log_task_success('cleanup_processed_requests_task', result)
    return result


@shared_task(name='wallet.tasks.cleanup_notifications_task', ignore_result=True)
def cleanup_notifications_task():
    _log_task_start('cleanup_notifications_task')
    result = cleanup_notifications()
    _log_task_success('cleanup_notifications_task', result)
    return result


@shared_task(name='wallet.tasks.archive_transfer_attempts_task', ignore_result=True)
def archive_transfer_attempts_task():
    _log_task_start('archive_transfer_attempts_task')
    result = archive_transfer_attempts()
    _log_task_success('archive_transfer_attempts_task', result)
    return result


@shared_task(
    name='wallet.tasks.send_notification_task',
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    ignore_result=True,
)
def send_notification_task(self, notification_id):
    _log_task_start('send_notification_task', notification_id=notification_id)
    try:
        result = deliver_notification(notification_id)
        _log_task_success('send_notification_task', result)
        return result
    except Exception as exc:
        _log_task_failure('send_notification_task', exc)
        raise self.retry(exc=exc)


@shared_task(
    name='wallet.tasks.process_mobile_money_webhook',
    bind=True,
    ignore_result=False,
    max_retries=5,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def process_mobile_money_webhook(self, provider_transaction_id, status, provider_response=None):
    _log_task_start(
        'process_mobile_money_webhook',
        provider_transaction_id=provider_transaction_id,
        status=status,
    )
    try:
        result = process_mobile_money_webhook_event(
            provider_transaction_id=provider_transaction_id,
            status=status,
            provider_response=provider_response,
        )
        _log_task_success('process_mobile_money_webhook', result)
        return result
    except Exception as exc:
        _log_task_failure('process_mobile_money_webhook', exc)
        raise self.retry(exc=exc)


@shared_task(
    name='wallet.tasks.broadcast_notification_task',
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    autoretry_for=(Exception,),
    retry_backoff=True,
)
def broadcast_notification_task(self, notification_type, payload, user_ids=None):
    _log_task_start('broadcast_notification_task', type=notification_type)
    try:
        result = broadcast_notification(notification_type, payload, user_ids=user_ids)
        _log_task_success('broadcast_notification_task', result)
        return result
    except Exception as exc:
        _log_task_failure('broadcast_notification_task', exc)
        raise self.retry(exc=exc)


@shared_task(
    name='wallet.tasks.refresh_exchange_rates_task',
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    ignore_result=True,
)
def refresh_exchange_rates_task(self):
    _log_task_start('refresh_exchange_rates_task')
    try:
        result = refresh_exchange_rates()
        _log_task_success('refresh_exchange_rates_task', result)
        if result.get('errors'):
            logger.error(json.dumps({'event': 'refresh_exchange_rates_errors', **result}))
        return result
    except Exception as exc:
        _log_task_failure('refresh_exchange_rates_task', exc)
        raise self.retry(exc=exc)


@shared_task(name='wallet.tasks.generate_transaction_export', ignore_result=False)
def generate_transaction_export(export_id, filters=None):
    """
    Placeholder for async CSV export once volume exceeds synchronous streaming.
    """
    _log_task_start('generate_transaction_export', export_id=export_id)
    result = {'export_id': export_id, 'status': 'not_implemented'}
    _log_task_success('generate_transaction_export', result)
    return result


@shared_task(name='wallet.tasks.generate_merchant_api_keys_task', ignore_result=True)
def generate_merchant_api_keys_task(merchant_id):
    """Ensure approved merchants have API key records for sandbox and live modes."""
    merchant = Merchant.objects.get(pk=merchant_id)
    for mode in (MerchantMode.SANDBOX, MerchantMode.LIVE):
        key = MerchantApiKey.objects.filter(merchant=merchant, mode=mode).first()
        if key:
            continue
        secret = secrets.token_urlsafe(32)
        public_key = f'{"live" if mode == MerchantMode.LIVE else "test"}_pk_{secrets.token_urlsafe(18)}'
        MerchantApiKey.objects.create(
            merchant=merchant,
            mode=mode,
            public_key=public_key,
            secret_key_prefix=f'{"live" if mode == MerchantMode.LIVE else "test"}_sk_',
            secret_key_hash=hashlib.sha256(secret.encode()).hexdigest(),
        )
    return {'merchant_id': merchant_id, 'status': 'ready'}


@shared_task(
    name='wallet.tasks.deliver_webhook_task',
    bind=True,
    max_retries=5,
    default_retry_delay=60,
    ignore_result=True,
)
def deliver_webhook_task(self, delivery_id):
    """Deliver a merchant webhook and retry failed deliveries."""
    try:
        return deliver_webhook(delivery_id)
    except Exception as exc:
        logger.warning('webhook_delivery_failed', extra={'delivery_id': delivery_id, 'error': str(exc)})
        raise self.retry(exc=exc)
