from django.core.management.base import BaseCommand
from django.db import IntegrityError, transaction
from django.db.models import Q

from wallet.models import Merchant, MerchantStatus, User, Wallet, WalletStatus
from wallet.services.merchants import merchant_public_identifier


class Command(BaseCommand):
    help = 'Create merchant records only for explicitly selected existing accounts.'

    def add_arguments(self, parser):
        parser.add_argument('--email', action='append', help='Merchant account email. May be supplied more than once.')
        parser.add_argument('--user-id', action='append', type=int, help='Merchant account user ID. May be supplied more than once.')
        parser.add_argument('--business-name', help='Business name when creating one merchant.')

    def handle(self, *args, **options):
        emails = [email.strip().lower() for email in (options.get('email') or []) if email.strip()]
        user_ids = options.get('user_id') or []
        if not emails and not user_ids:
            self.stdout.write(self.style.WARNING(
                'No accounts selected. Use --email merchant@example.com or --user-id USER_ID. '
                'No merchants were created because ordinary wallet users must not be promoted automatically.'
            ))
            return

        users = User.objects.filter(is_active=True).filter(
            Q(email__in=emails) | Q(id__in=user_ids)
        ).order_by('id')
        requested_count = len(set(emails)) + len(set(user_ids))
        found_ids = set(users.values_list('id', flat=True))
        if len(found_ids) < requested_count:
            self.stdout.write(self.style.WARNING('One or more selected accounts were not found or inactive.'))

        created = 0
        for user in users.iterator():
            if hasattr(user, 'merchant_account'):
                merchant_public_identifier(user.merchant_account)
                self.stdout.write(f'Existing merchant {user.merchant_account.id} unchanged for {user.email}')
                continue

            try:
                with transaction.atomic():
                    wallet = Wallet.objects.filter(user=user, is_sandbox=False).first()
                    if not wallet:
                        wallet = Wallet.objects.create(user=user, currency='GNF', status=WalletStatus.ACTIVE)
                    merchant = Merchant.objects.create(
                        user=user,
                        business_name=options.get('business_name') or user.display_name or user.handle,
                        business_email=user.email,
                        wallet=wallet,
                        status=MerchantStatus.PENDING,
                    )
                    merchant_public_identifier(merchant)
            except IntegrityError:
                merchant = Merchant.objects.filter(user=user).first()
                if merchant:
                    merchant_public_identifier(merchant)
                    self.stdout.write(f'Existing merchant {merchant.id} unchanged for {user.email}')
                    continue
                raise
            created += 1
            self.stdout.write(f'Created merchant {merchant.id} for {user.email}')
        self.stdout.write(self.style.SUCCESS(f'{created} merchant(s) created; existing merchants unchanged.'))
