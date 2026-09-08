from decimal import Decimal

from django.db import migrations, models


def convert_existing_currency(apps, schema_editor):
    Wallet = apps.get_model('wallet', 'Wallet')
    MerchantPlan = apps.get_model('wallet', 'MerchantPlan')
    Wallet.objects.filter(currency='USD').update(currency='GNF')
    MerchantPlan.objects.filter(currency='USD').update(currency='GNF')
    MerchantPlan.objects.filter(code='growth').update(monthly_price=Decimal('290000.00'))
    MerchantPlan.objects.filter(code='scale').update(monthly_price=Decimal('990000.00'))


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0014_merchant_plans_subscriptions'),
    ]

    operations = [
        migrations.AlterField(
            model_name='wallet',
            name='currency',
            field=models.CharField(default='GNF', max_length=3),
        ),
        migrations.AlterField(
            model_name='merchantplan',
            name='currency',
            field=models.CharField(default='GNF', max_length=3),
        ),
        migrations.RunPython(convert_existing_currency, migrations.RunPython.noop),
    ]
