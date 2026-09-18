from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0038_merchant_payment_intent_hardening'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='webhook_events',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
