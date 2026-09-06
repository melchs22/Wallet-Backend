from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Idempotent alias for setup_celery_beat — registers all periodic tasks'

    def handle(self, *args, **options):
        call_command('setup_celery_beat')
