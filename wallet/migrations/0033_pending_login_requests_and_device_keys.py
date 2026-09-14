from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('wallet', '0032_add_transaction_fees'),
    ]

    operations = [
        migrations.AddField(
            model_name='trusteddevice',
            name='public_key_pem',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.CreateModel(
            name='PendingLoginRequest',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('new_device_id', models.CharField(max_length=255)),
                ('new_device_name', models.CharField(blank=True, default='', max_length=120)),
                ('new_device_public_key_pem', models.TextField()),
                ('requesting_ip', models.GenericIPAddressField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('denied', 'Denied'), ('expired', 'Expired')], default='pending', max_length=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('resolved_at', models.DateTimeField(blank=True, null=True)),
                ('resolved_by_device', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='resolved_login_requests', to='wallet.trusteddevice')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pending_login_requests', to='wallet.user')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['user', 'status', 'created_at'], name='wallet_pendi_user_id_8c5a5b_idx')],
            },
        ),
    ]
