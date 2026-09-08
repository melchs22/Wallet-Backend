import os
from django.core.management.base import BaseCommand
from django.db import transaction
from django.conf import settings
from wallet.models import User, Wallet, KYCTier, UserStatus, WalletStatus, LedgerEntry, LedgerDirection
from decimal import Decimal


class Command(BaseCommand):
    help = 'Create a default admin user with username and password'

    def add_arguments(self, parser):
        parser.add_argument(
            '--username',
            type=str,
            default=os.getenv('DEFAULT_ADMIN_USERNAME', 'TUTU'),
            help='Admin username (default from env DEFAULT_ADMIN_USERNAME or TUTU)'
        )
        parser.add_argument(
            '--password',
            type=str,
            default=os.getenv('DEFAULT_ADMIN_PASSWORD', 'tutu2005'),
            help='Admin password (default from env DEFAULT_ADMIN_PASSWORD or tutu2005)'
        )
        parser.add_argument(
            '--email',
            type=str,
            default='admin@kesho.wallet',
            help='Admin email (default: admin@kesho.wallet)'
        )

    def handle(self, *args, **options):
        username = options['username']
        password = options['password']
        email = options['email']

        try:
            with transaction.atomic():
                if User.objects.filter(username=username).exists():
                    self.stdout.write(
                        self.style.WARNING(f'Admin user "{username}" already exists.')
                    )
                    return

                if User.objects.filter(email=email).exists():
                    self.stdout.write(
                        self.style.WARNING(f'User with email "{email}" already exists.')
                    )
                    return

                user = User.objects.create_admin_user(
                    username=username,
                    password=password,
                    email=email,
                    kyc_tier=KYCTier.TIER_2,
                    status=UserStatus.ACTIVE,
                    must_change_password=True,
                )

                wallet = Wallet.objects.create(
                    user=user,
                    currency='GNF',
                    status=WalletStatus.ACTIVE,
                )

                LedgerEntry.objects.create(
                    wallet=wallet,
                    transaction=None,
                    direction=LedgerDirection.CREDIT,
                    amount=Decimal('0.00'),
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f'Successfully created admin user:\n'
                        f'  Username: {username}\n'
                        f'  Email: {email}\n'
                        f'  Password: {password}\n'
                        f'  is_staff: {user.is_staff}\n'
                        f'  must_change_password: {user.must_change_password}\n'
                        f'  KYC Tier: {user.kyc_tier}'
                    )
                )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Error creating admin user: {str(e)}')
            )
            raise