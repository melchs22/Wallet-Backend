# Generated manually to keep production deployments migration-safe.
import django.db.models.deletion
import wallet.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('wallet', '0004_exchangerate_linkedprovider_transferattempt_and_more')]

    operations = [
        migrations.CreateModel(
            name='PaymentRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('currency', models.CharField(max_length=3)),
                ('note', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('paid', 'Paid'), ('declined', 'Declined'), ('cancelled', 'Cancelled'), ('expired', 'Expired')], default='pending', max_length=20)),
                ('expires_at', models.DateTimeField(default=wallet.models.default_request_expiry)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('payer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='requests_received', to=settings.AUTH_USER_MODEL)),
                ('requester', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='requests_sent', to=settings.AUTH_USER_MODEL)),
                ('resulting_transaction', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='fulfilled_requests', to='wallet.transaction')),
            ],
            options={'db_table': 'payment_requests', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='SplitRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('currency', models.CharField(max_length=3)),
                ('note', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('creator', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='splits_created', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'split_requests', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='SplitParticipant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount_owed', models.DecimalField(decimal_places=2, max_digits=20)),
                ('payment_request', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='split_participant', to='wallet.paymentrequest')),
                ('split_request', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='participants', to='wallet.splitrequest')),
            ],
            options={'db_table': 'split_participants'},
        ),
        migrations.AddIndex(model_name='paymentrequest', index=models.Index(fields=['requester', 'status', 'created_at'], name='payment_req_request_26a1ee_idx')),
        migrations.AddIndex(model_name='paymentrequest', index=models.Index(fields=['payer', 'status', 'created_at'], name='payment_req_payer_i_0cc8f0_idx')),
    ]
