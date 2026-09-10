from decimal import Decimal

from django.db import migrations, models


def seed_withdrawal_fees(apps, schema_editor):
    TransferFeeRule = apps.get_model('wallet', 'TransferFeeRule')
    rules = [
        (Decimal('2000'), Decimal('50000'), 'flat', Decimal('1000')),
        (Decimal('50001'), Decimal('1700000'), 'percentage', Decimal('2')),
        (Decimal('1700001'), Decimal('3200000'), 'percentage', Decimal('1.5')),
        (Decimal('3200001'), Decimal('12000000'), 'percentage', Decimal('1')),
        (Decimal('12000001'), Decimal('15000000'), 'flat', Decimal('120000')),
    ]
    for minimum, maximum, fee_type, fee_value in rules:
        TransferFeeRule.objects.get_or_create(
            min_amount=minimum,
            max_amount=maximum,
            defaults={'fee_type': fee_type, 'fee_value': fee_value, 'active': True},
        )


class Migration(migrations.Migration):
    dependencies = [('wallet', '0028_transactionapproval_metadata_user_current_device_id')]
    operations = [
        migrations.AddField(
            model_name='mobilemoneytransaction',
            name='fee_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=20),
        ),
        migrations.RunPython(seed_withdrawal_fees, migrations.RunPython.noop),
    ]