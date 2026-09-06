from django.core.management.base import BaseCommand

from wallet.services.transfers import run_scheduled_transfers


class Command(BaseCommand):
    help = 'Process scheduled transfers that are due for execution'

    def handle(self, *args, **options):
        self.stdout.write('Processing scheduled transfers...')
        result = run_scheduled_transfers()
        self.stdout.write(
            self.style.SUCCESS(
                f'Completed: {result["processed_count"]} processed, '
                f'{result["failed_count"]} failed, {result["skipped_count"]} skipped'
            )
        )
