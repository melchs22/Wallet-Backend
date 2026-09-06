from django.core.management.base import BaseCommand
from celery import current_app


class Command(BaseCommand):
    help = 'Run a Celery task synchronously by name (uses Celery apply, not the queue)'

    def add_arguments(self, parser):
        parser.add_argument('task_name', type=str, help='Task name, e.g. expire_payment_requests')

    def handle(self, *args, **options):
        task_name = options['task_name']
        task_map = {
            'expire_payment_requests': 'wallet.tasks.expire_payment_intents_task',
            'expire_payment_intents': 'wallet.tasks.expire_payment_intents_task',
            'reconcile_balances': 'wallet.tasks.reconcile_balances_task',
            'refresh_exchange_rates': 'wallet.tasks.refresh_exchange_rates_task',
            'health_check': 'wallet.tasks.health_check_task',
        }
        celery_task_name = task_map.get(task_name, task_name)
        if not celery_task_name.startswith('wallet.tasks.'):
            celery_task_name = f'wallet.tasks.{celery_task_name}_task'

        result = current_app.send_task(celery_task_name).get()
        self.stdout.write(self.style.SUCCESS(f'Task {celery_task_name} completed: {result}'))
