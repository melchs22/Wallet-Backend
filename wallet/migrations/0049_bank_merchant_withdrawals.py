from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('wallet', '0048_pushdevice_language_code')]

    operations = [
        migrations.CreateModel(
            name='Bank',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('code', models.CharField(max_length=30, unique=True)),
                ('logo_url', models.URLField(blank=True, default='')),
                ('country_code', models.CharField(default='GN', max_length=2)),
                ('currency', models.CharField(default='GNF', max_length=3)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={'ordering': ['name']},
        ),
        migrations.CreateModel(
            name='MerchantBankAccount',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('account_name', models.CharField(max_length=160)),
                ('account_number', models.CharField(max_length=80)),
                ('is_verified', models.BooleanField(default=False)),
                ('is_default', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('bank', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='merchant_accounts', to='wallet.bank')),
                ('merchant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bank_accounts', to='wallet.merchant')),
            ],
            options={'ordering': ['-is_default', '-created_at']},
        ),
        migrations.CreateModel(
            name='MerchantWithdrawal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('fee_amount', models.DecimalField(decimal_places=2, default='0.00', max_digits=20)),
                ('currency', models.CharField(max_length=3)),
                ('reference', models.CharField(max_length=100, unique=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('provider_response', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('bank_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='withdrawals', to='wallet.merchantbankaccount')),
                ('merchant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='withdrawals', to='wallet.merchant')),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
