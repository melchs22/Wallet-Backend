from decimal import Decimal

from django.db import migrations, models
import django.db.models.deletion


def seed_plans(apps, schema_editor):
    MerchantPlan = apps.get_model('wallet', 'MerchantPlan')
    plans = [
        {
            'code': 'starter',
            'name': 'Starter',
            'description': 'For new businesses validating digital checkout.',
            'monthly_price': Decimal('0.00'),
            'monthly_transaction_limit': 100,
            'transaction_fee_percent': Decimal('1.500'),
            'api_access': False,
            'webhook_access': False,
        },
        {
            'code': 'growth',
            'name': 'Growth',
            'description': 'For growing teams running regular wallet payments.',
            'monthly_price': Decimal('29.00'),
            'monthly_transaction_limit': 5000,
            'transaction_fee_percent': Decimal('0.900'),
            'api_access': True,
            'webhook_access': True,
        },
        {
            'code': 'scale',
            'name': 'Scale',
            'description': 'For high-volume businesses and platform partners.',
            'monthly_price': Decimal('99.00'),
            'monthly_transaction_limit': None,
            'transaction_fee_percent': Decimal('0.500'),
            'api_access': True,
            'webhook_access': True,
        },
    ]
    for plan in plans:
        MerchantPlan.objects.update_or_create(code=plan['code'], defaults=plan)


def remove_plans(apps, schema_editor):
    apps.get_model('wallet', 'MerchantPlan').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0015_merchant_credentials'),
    ]

    operations = [
        migrations.CreateModel(
            name='MerchantPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.SlugField(max_length=30, unique=True)),
                ('name', models.CharField(max_length=80)),
                ('description', models.TextField(blank=True, default='')),
                ('monthly_price', models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12)),
                ('currency', models.CharField(default='USD', max_length=3)),
                ('monthly_transaction_limit', models.PositiveIntegerField(blank=True, null=True)),
                ('transaction_fee_percent', models.DecimalField(decimal_places=3, default=Decimal('0.000'), max_digits=6)),
                ('api_access', models.BooleanField(default=False)),
                ('webhook_access', models.BooleanField(default=False)),
                ('qr_payments', models.BooleanField(default=True)),
                ('kyc_support', models.BooleanField(default=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'db_table': 'merchant_plans', 'ordering': ['monthly_price', 'id']},
        ),
        migrations.CreateModel(
            name='MerchantSubscription',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('trialing', 'Trialing'), ('active', 'Active'), ('past_due', 'Past due'), ('canceled', 'Canceled')], default='trialing', max_length=20)),
                ('current_period_start', models.DateTimeField()),
                ('current_period_end', models.DateTimeField()),
                ('cancel_at_period_end', models.BooleanField(default=False)),
                ('provider_reference', models.CharField(blank=True, default='', max_length=120)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('merchant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='subscription', to='wallet.merchant')),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='subscriptions', to='wallet.merchantplan')),
            ],
            options={'db_table': 'merchant_subscriptions'},
        ),
        migrations.RunPython(seed_plans, remove_plans),
    ]
