from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0037_supportedcountry_currency'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentintent',
            name='idempotency_key',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddIndex(
            model_name='paymentintent',
            index=models.Index(fields=['merchant', 'mode', 'idempotency_key'], name='wallet_payme_merchan_9e2c75_idx'),
        ),
        migrations.AddConstraint(
            model_name='paymentintent',
            constraint=models.UniqueConstraint(
                condition=models.Q(('idempotency_key__isnull', False)),
                fields=('merchant', 'mode', 'idempotency_key'),
                name='unique_merchant_intent_idempotency',
            ),
        ),
        migrations.AlterField(
            model_name='webhookdelivery',
            name='payment_intent',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='webhook_deliveries',
                to='wallet.paymentintent',
            ),
        ),
    ]
