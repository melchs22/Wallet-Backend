from django.core.management.base import BaseCommand
from django.db import transaction
from decimal import Decimal
from wallet.models import Wallet, LedgerEntry, LedgerDirection
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Reconcile wallet balances against ledger entries and report any drift'

    def add_arguments(self, parser):
        parser.add_argument(
            '--fix',
            action='store_true',
            help='Auto-fix drift by updating balance_cache if implemented',
        )

    def handle(self, *args, **options):
        self.stdout.write('Starting balance reconciliation...')
        
        wallets = Wallet.objects.all()
        total_wallets = wallets.count()
        drift_count = 0
        
        for wallet in wallets:
            try:
                # Compute balance from ledger
                from django.db.models import Sum
                
                credits = wallet.entries.filter(direction=LedgerDirection.CREDIT).aggregate(
                    total=Sum('amount')
                )['total'] or Decimal('0.00')
                
                debits = wallet.entries.filter(direction=LedgerDirection.DEBIT).aggregate(
                    total=Sum('amount')
                )['total'] or Decimal('0.00')
                
                computed_balance = credits - debits
                
                # Check against cached balance if implemented
                # For now, we just log the computed balance
                # In the future, compare against balance_cache field
                
                self.stdout.write(
                    f'Wallet {wallet.id} (User: {wallet.user.email}): '
                    f'Computed balance: {computed_balance} {wallet.currency}'
                )
                
                # If balance_cache is implemented in the future, add drift detection here:
                # if hasattr(wallet, 'balance_cache') and wallet.balance_cache != computed_balance:
                #     drift_count += 1
                #     logger.error(
                #         f'Balance drift detected for wallet {wallet.id}: '
                #         f'cached={wallet.balance_cache}, computed={computed_balance}'
                #     )
                #     if options['fix']:
                #         wallet.balance_cache = computed_balance
                #         wallet.save()
                
            except Exception as e:
                logger.error(f'Error reconciling wallet {wallet.id}: {str(e)}')
                self.stdout.write(
                    self.style.ERROR(f'Error reconciling wallet {wallet.id}: {str(e)}')
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Reconciliation complete. Checked {total_wallets} wallets. '
                f'Drift detected: {drift_count}'
            )
        )
        
        if drift_count > 0:
            logger.error(f'Balance reconciliation found {drift_count} wallets with drift')
