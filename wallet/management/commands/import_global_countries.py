import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from wallet.models import SupportedCountry


def flag_for_code(code):
    return ''.join(chr(127397 + ord(letter)) for letter in code.upper() if 'A' <= letter <= 'Z')


class Command(BaseCommand):
    help = 'Import country metadata and currencies from global_countries.json.'

    def add_arguments(self, parser):
        parser.add_argument('path', nargs='?', default='global_countries.json')

    def handle(self, *args, **options):
        path = Path(options['path'])
        if not path.exists():
            raise CommandError(f'Country file not found: {path}')
        try:
            countries = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f'Could not read country file: {exc}') from exc

        created = updated = currencies_updated = 0
        for country in countries:
            code = str(country.get('cca2', '')).upper()
            if len(code) != 2:
                continue
            idd = country.get('idd') or {}
            root = idd.get('root') or ''
            suffixes = idd.get('suffixes') or []
            dial_code = f'{root}{suffixes[0]}' if root and suffixes else root
            currencies = country.get('currencies') or {}
            currency = next((str(code).upper() for code in currencies if len(str(code)) == 3), 'GNF')
            defaults = {
                'name': ((country.get('name') or {}).get('common') or code)[:100],
                'dial_code': dial_code[:8],
                'flag': flag_for_code(code),
                'active': True,
                'currency': currency,
            }
            existing = SupportedCountry.objects.filter(code=code).first()
            if existing:
                changed = [field for field, value in defaults.items() if getattr(existing, field) != value]
                for field in changed:
                    setattr(existing, field, defaults[field])
                if changed:
                    existing.save(update_fields=changed)
                    updated += 1
                    currencies_updated += int('currency' in changed)
                continue
            SupportedCountry.objects.create(code=code, **defaults)
            created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Imported {created + updated} countries ({created} created, {updated} updated, '
            f'{currencies_updated} currencies updated).'
        ))