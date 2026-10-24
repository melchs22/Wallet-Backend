from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('wallet', '0052_user_language_code')]

    operations = [
        migrations.AddField(
            model_name='scheduledtransfer',
            name='name',
            field=models.CharField(blank=True, default='', max_length=120),
        ),
        migrations.CreateModel(
            name='UtilityPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('service', models.CharField(choices=[('water', 'Water Bill'), ('electricity', 'Electricity')], max_length=20)),
                ('account_number', models.CharField(max_length=80)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('currency', models.CharField(max_length=3)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('provider_reference', models.CharField(max_length=100, unique=True)),
                ('provider_response', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='utility_payments', to='wallet.user')),
                ('wallet', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='utility_payments', to='wallet.wallet')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='utilitypayment',
            index=models.Index(fields=['user', 'service', 'created_at'], name='wallet_utili_user_id_6a9a7f_idx'),
        ),
    ]
