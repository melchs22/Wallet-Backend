from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0045_transaction_merchant_fee_amount'),
    ]

    operations = [
        migrations.AddField(
            model_name='mobilemoneytransaction',
            name='destination_phone',
            field=models.CharField(
                blank=True,
                default='',
                help_text='External recipient phone; no wallet account is created for this recipient.',
                max_length=30,
            ),
        ),
    ]
