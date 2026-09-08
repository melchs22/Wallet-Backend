from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0023_pushdevice'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='transaction_pin',
            field=models.CharField(blank=True, help_text='Hashed 4-digit PIN for transaction approvals', max_length=128, null=True),
        ),
    ]