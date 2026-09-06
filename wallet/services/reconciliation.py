import json
import logging
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from wallet.models import LedgerDirection, SystemSetting, Wallet

logger = logging.getLogger(__name__)

RECONCILIATION_SETTING_KEY = 'reconciliation_last_run'


def reconcile_balances(fix=False):
    """
    Reconcile wallet balances against ledger entries.
    Stores the last run result in SystemSetting for the admin dashboard.
    """
    wallets = Wallet.objects.select_related('user').filter(is_sandbox=False)
    total_wallets = wallets.count()
    drift_count = 0
    drift_details = []
    errors = []

    for wallet in wallets:
        try:
            credits = wallet.entries.filter(direction=LedgerDirection.CREDIT).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00')

            debits = wallet.entries.filter(direction=LedgerDirection.DEBIT).aggregate(
                total=Sum('amount')
            )['total'] or Decimal('0.00')

            computed_balance = credits - debits

            if hasattr(wallet, 'balance_cache'):
                cached = wallet.balance_cache
                if cached != computed_balance:
                    drift_count += 1
                    detail = {
                        'wallet_id': wallet.id,
                        'user_handle': wallet.user.handle,
                        'cached': str(cached),
                        'computed': str(computed_balance),
                    }
                    drift_details.append(detail)
                    logger.error(
                        'balance_drift_detected',
                        extra={'wallet_id': wallet.id, 'cached': str(cached), 'computed': str(computed_balance)},
                    )
                    if fix:
                        wallet.balance_cache = computed_balance
                        wallet.save(update_fields=['balance_cache'])
        except Exception as exc:
            logger.exception('reconcile_wallet_error', extra={'wallet_id': wallet.id})
            errors.append({'wallet_id': wallet.id, 'error': str(exc)})

    result = {
        'run_at': timezone.now().isoformat(),
        'total_wallets': total_wallets,
        'drift_count': drift_count,
        'drift_details': drift_details,
        'errors': errors,
        'status': 'drift_detected' if drift_count else ('partial_failure' if errors else 'ok'),
    }

    if drift_count:
        logger.error(
            json.dumps({'event': 'reconcile_balances_drift', 'drift_count': drift_count, **result})
        )

    SystemSetting.objects.update_or_create(
        key=RECONCILIATION_SETTING_KEY,
        defaults={
            'value': json.dumps(result),
            'description': 'Last balance reconciliation run result (JSON)',
        },
    )

    return result


def get_reconciliation_last_run():
    """Return the stored last-run result, or None if never run."""
    try:
        setting = SystemSetting.objects.get(key=RECONCILIATION_SETTING_KEY)
        return json.loads(setting.value)
    except (SystemSetting.DoesNotExist, json.JSONDecodeError):
        return None
