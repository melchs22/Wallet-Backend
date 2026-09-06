from django.core.management.base import BaseCommand

from wallet.services.reconciliation import reconcile_balances


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
        result = reconcile_balances(fix=options['fix'])

        self.stdout.write(
            self.style.SUCCESS(
                f'Reconciliation complete. Checked {result["total_wallets"]} wallets. '
                f'Drift detected: {result["drift_count"]}. Status: {result["status"]}.'
            )
        )

        if result['drift_count'] > 0:
            for detail in result['drift_details']:
                self.stdout.write(self.style.ERROR(str(detail)))
