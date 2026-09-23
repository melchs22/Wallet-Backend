from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0049_bank_merchant_withdrawals'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchantapikey',
            name='secret_key_encrypted',
            field=models.TextField(blank=True, default=''),
        ),
    ]
