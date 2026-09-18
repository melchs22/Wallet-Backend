from django.core.management.base import BaseCommand

from wallet.services.exchange_rates import refresh_exchange_rates


class Command(BaseCommand):
    help = 'Fetch latest exchange rates from exchangerate.fun and store them'

    def add_arguments(self, parser):
        parser.add_argument(
            '--base',
            action='append',
            dest='bases',
            help='Base currency to fetch (can be repeated). Defaults to active wallet currencies.',
        )

    def handle(self, *args, **options):
        bases = options.get('bases') or None
        self.stdout.write('Fetching exchange rates from exchangerate.fun...')
        result = refresh_exchange_rates(base_currencies=bases)

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Created {result["created_count"]} rates, '
                f'skipped {result["skipped_count"]}, '
                f'errors {len(result["errors"])}, '
                f'missing pairs {len(result.get("missing_pairs", []))}.'
            )
        )

        if result['errors']:
            for err in result['errors']:
                self.stdout.write(self.style.ERROR(str(err)))
        if result.get('missing_pairs'):
            self.stdout.write(
                self.style.WARNING(
                    'The rate provider did not return these pairs: '
                    + ', '.join(result['missing_pairs'])
                )
            )
