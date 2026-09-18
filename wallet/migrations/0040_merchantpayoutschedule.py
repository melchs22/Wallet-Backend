from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('wallet', '0039_merchant_webhook_events')]

    operations = [migrations.CreateModel(
        name='MerchantPayoutSchedule',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('frequency', models.CharField(choices=[('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly')], default='daily', max_length=20)),
            ('destination', models.CharField(blank=True, default='', max_length=255)),
            ('enabled', models.BooleanField(default=True)),
            ('next_payout_at', models.DateTimeField(blank=True, null=True)),
            ('last_payout_at', models.DateTimeField(blank=True, null=True)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('merchant', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='payout_schedule', to='wallet.merchant')),
        ],
        options={'db_table': 'merchant_payout_schedules'},
    )]
