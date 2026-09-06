from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('wallet', '0013_merchant_payment_api')]
    operations = [
        migrations.CreateModel(
            name='KYCDocument',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('document_type', models.CharField(choices=[('registration', 'Business registration'), ('owner_id', 'Owner identity'), ('tax_id', 'Tax document'), ('settlement', 'Settlement destination')], max_length=30)),
                ('file_url', models.URLField()),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('reupload', 'Re-upload required')], default='pending', max_length=20)),
                ('reviewer_notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('merchant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='kyc_documents', to='wallet.merchant')),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_kyc_documents', to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'wallet_kyc_documents', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='Settlement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=20)),
                ('fees', models.DecimalField(decimal_places=2, default=0, max_digits=20)),
                ('currency', models.CharField(max_length=3)),
                ('batch_reference', models.CharField(max_length=100, unique=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('processing', 'Processing'), ('completed', 'Completed'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('destination', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('merchant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='settlements', to='wallet.merchant')),
            ],
            options={'db_table': 'wallet_settlements', 'ordering': ['-created_at']},
        ),
    ]