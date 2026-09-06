from django.core.management.base import BaseCommand
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask


PERIODIC_TASKS = [
    {
        'name': 'expire_payment_intents',
        'task': 'wallet.tasks.expire_payment_intents_task',
        'interval': {'every': 10, 'period': IntervalSchedule.MINUTES},
        'description': 'Mark payment intents past expires_at as expired',
    },
    {
        'name': 'expire_payment_requests',
        'task': 'wallet.tasks.expire_payment_requests_task',
        'interval': {'every': 10, 'period': IntervalSchedule.MINUTES},
        'description': 'Mark payment requests past expires_at as expired',
    },
    {
        'name': 'run_scheduled_transfers',
        'task': 'wallet.tasks.run_scheduled_transfers_task',
        'interval': {'every': 5, 'period': IntervalSchedule.MINUTES},
        'description': 'Execute due recurring/scheduled transfers',
    },
    {
        'name': 'reconcile_balances',
        'task': 'wallet.tasks.reconcile_balances_task',
        'crontab': {'minute': '0', 'hour': '2', 'day_of_week': '*', 'day_of_month': '*', 'month_of_year': '*'},
        'description': 'Nightly balance reconciliation against ledger',
    },
    {
        'name': 'clear_expired_sessions',
        'task': 'wallet.tasks.clear_expired_sessions_task',
        'crontab': {'minute': '30', 'hour': '3', 'day_of_week': '*', 'day_of_month': '*', 'month_of_year': '*'},
        'description': 'Remove expired Django sessions',
    },
    {
        'name': 'cleanup_processed_requests',
        'task': 'wallet.tasks.cleanup_processed_requests_task',
        'crontab': {'minute': '0', 'hour': '4', 'day_of_week': '0', 'day_of_month': '*', 'month_of_year': '*'},
        'description': 'Delete ProcessedRequest rows older than 90 days',
    },
    {
        'name': 'cleanup_notifications',
        'task': 'wallet.tasks.cleanup_notifications_task',
        'crontab': {'minute': '15', 'hour': '4', 'day_of_week': '0', 'day_of_month': '*', 'month_of_year': '*'},
        'description': 'Delete read notifications older than 60 days',
    },
    {
        'name': 'archive_transfer_attempts',
        'task': 'wallet.tasks.archive_transfer_attempts_task',
        'crontab': {'minute': '0', 'hour': '5', 'day_of_month': '1', 'day_of_week': '*', 'month_of_year': '*'},
        'description': 'Archive transfer attempt rows older than 1 year',
    },
    {
        'name': 'refresh_exchange_rates',
        'task': 'wallet.tasks.refresh_exchange_rates_task',
        'crontab': {'minute': '0', 'hour': '*', 'day_of_week': '*', 'day_of_month': '*', 'month_of_year': '*'},
        'description': 'Hourly FX rate pull from exchangerate.fun',
    },
    {
        'name': 'celery_health_check',
        'task': 'wallet.tasks.health_check_task',
        'interval': {'every': 60, 'period': IntervalSchedule.MINUTES},
        'description': 'Pipeline health check — remove once stable',
        'enabled': False,
    },
]


class Command(BaseCommand):
    help = 'Register periodic Celery Beat tasks in the database (django-celery-beat)'

    def handle(self, *args, **options):
        created = 0
        updated = 0

        for spec in PERIODIC_TASKS:
            schedule = None
            if 'interval' in spec:
                schedule, _ = IntervalSchedule.objects.get_or_create(**spec['interval'])
            elif 'crontab' in spec:
                schedule, _ = CrontabSchedule.objects.get_or_create(**spec['crontab'])

            defaults = {
                'task': spec['task'],
                'enabled': spec.get('enabled', True),
                'description': spec.get('description', ''),
            }
            if isinstance(schedule, IntervalSchedule):
                defaults['interval'] = schedule
                defaults['crontab'] = None
            else:
                defaults['crontab'] = schedule
                defaults['interval'] = None

            task, was_created = PeriodicTask.objects.update_or_create(
                name=spec['name'],
                defaults=defaults,
            )

            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f'Created periodic task: {spec["name"]}'))
            else:
                updated += 1
                self.stdout.write(f'Updated periodic task: {spec["name"]}')

        self.stdout.write(
            self.style.SUCCESS(f'Done. Created {created}, updated {updated} periodic tasks.')
        )
