import uuid

from django.db import migrations, models
import django.db.models.deletion
import wallet.models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0054_admintotp'),
    ]

    operations = [
        migrations.CreateModel(
            name='NearbyPaymentRequest',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('code_digest', models.CharField(max_length=64, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('currency', models.CharField(max_length=3)),
                ('note', models.CharField(blank=True, default='', max_length=500)),
                ('status', models.CharField(
                    choices=[
                        ('open', 'Open'),
                        ('paid', 'Paid'),
                        ('cancelled', 'Cancelled'),
                        ('expired', 'Expired'),
                    ],
                    default='open',
                    max_length=12,
                )),
                ('expires_at', models.DateTimeField(default=wallet.models.default_request_expiry)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('idempotency_hash', models.CharField(blank=True, default='', max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('payer', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='nearby_payments_made',
                    to='wallet.user',
                )),
                ('receiver', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='nearby_payment_requests',
                    to='wallet.user',
                )),
                ('resulting_transaction', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='nearby_payment_requests',
                    to='wallet.transaction',
                )),
            ],
            options={
                'db_table': 'nearby_payment_requests',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='nearbypaymentrequest',
            index=models.Index(fields=['receiver', 'status', 'created_at'], name='nearby_pay_receiver_idx'),
        ),
        migrations.AddIndex(
            model_name='nearbypaymentrequest',
            index=models.Index(fields=['status', 'expires_at'], name='nearby_pay_status_expiry_idx'),
        ),
    ]
