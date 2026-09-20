from django.db import migrations, models
from decimal import Decimal


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0044_otp_dev_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='merchant_fee_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                max_digits=20,
            ),
        ),
    ]
