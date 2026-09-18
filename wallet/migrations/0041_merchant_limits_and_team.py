from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from decimal import Decimal


class Migration(migrations.Migration):
    dependencies = [('wallet', '0040_merchantpayoutschedule')]

    operations = [
        migrations.CreateModel(
            name='MerchantLimit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('currency', models.CharField(default='GNF', max_length=3)),
                ('per_transaction', models.DecimalField(decimal_places=2, default=Decimal('100000.00'), max_digits=20)),
                ('daily', models.DecimalField(decimal_places=2, default=Decimal('1000000.00'), max_digits=20)),
                ('monthly', models.DecimalField(decimal_places=2, default=Decimal('10000000.00'), max_digits=20)),
                ('is_active', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('merchant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transaction_limits', to='wallet.merchant')),
            ],
            options={'db_table': 'merchant_limits'},
        ),
        migrations.CreateModel(
            name='MerchantTeamMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('role', models.CharField(choices=[('owner', 'Owner'), ('admin', 'Admin'), ('finance', 'Finance'), ('support', 'Support'), ('developer', 'Developer')], default='support', max_length=20)),
                ('is_active', models.BooleanField(default=True)),
                ('invited_at', models.DateTimeField(auto_now_add=True)),
                ('accepted_at', models.DateTimeField(blank=True, null=True)),
                ('invited_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sent_merchant_invitations', to=settings.AUTH_USER_MODEL)),
                ('merchant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='team_members', to='wallet.merchant')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='merchant_team_memberships', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'merchant_team_members'},
        ),
        migrations.AddConstraint(
            model_name='merchantlimit',
            constraint=models.UniqueConstraint(fields=('merchant', 'currency'), name='unique_merchant_limit_currency'),
        ),
        migrations.AddConstraint(
            model_name='merchantteammember',
            constraint=models.UniqueConstraint(fields=('merchant', 'email'), name='unique_merchant_team_email'),
        ),
        migrations.AddIndex(
            model_name='merchantteammember',
            index=models.Index(fields=['merchant', 'is_active', 'role'], name='merchant_te_merchant_4b6ad8_idx'),
        ),
    ]
