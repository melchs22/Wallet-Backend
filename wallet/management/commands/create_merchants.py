from django.core.management.base import BaseCommand
from django.db import transaction

from wallet.models import Merchant, MerchantStatus, User, Wallet, WalletStatus
from wallet.services.merchants import merchant_public_identifier


class Command(BaseCommand):
    help = 'Create merchant records for existing accounts, safely and idempotently.'

    def add_arguments(self, parser):
        parser.add_argument('--email', help='Only create a merchant for this account.')
        parser.add_argument('--business-name', help='Business name when creating one merchant.')

    def handle(self, *args, **options):
        users = User.objects.filter(is_active=True).order_by('id')
        if options.get('email'):
            users = users.filter(email__iexact=options['email'])
        created = 0
        for user in users.iterator():
            if hasattr(user, 'merchant_account'):
                merchant_public_identifier(user.merchant_account)
                continue
            wallet = Wallet.objects.filter(user=user, is_sandbox=False).first()
            if not wallet:
                wallet = Wallet.objects.create(user=user, currency='GNF', status=WalletStatus.ACTIVE)
            with transaction.atomic():
                merchant = Merchant.objects.create(
                    user=user,
                    business_name=options.get('business_name') or user.display_name or user.handle,
                    business_email=user.email,
                    wallet=wallet,
                    status=MerchantStatus.PENDING,
                )
                merchant_public_identifier(merchant)
            created += 1
            self.stdout.write(f'Created merchant {merchant.id} for {user.email}')
        self.stdout.write(self.style.SUCCESS(f'{created} merchant(s) created; existing merchants unchanged.'))
