from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('wallet', '0053_scheduled_transfer_name_utility_payment')]

    operations = [
        migrations.CreateModel(
            name='AdminTOTP',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('secret_encrypted', models.TextField(blank=True, default='')),
                ('setup_token_hash', models.CharField(blank=True, default='', max_length=256)),
                ('is_enabled', models.BooleanField(default=False)),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='admin_totp', to='wallet.user')),
            ],
        ),
    ]
