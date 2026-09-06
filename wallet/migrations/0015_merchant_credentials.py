from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('wallet', '0014_kyc_settlement')]
    operations = [
        migrations.AddField(model_name='merchant', name='sandbox_public_key', field=models.CharField(blank=True, default='', max_length=80)),
        migrations.AddField(model_name='merchant', name='sandbox_secret_hash', field=models.CharField(blank=True, default='', max_length=128)),
        migrations.AddField(model_name='merchant', name='live_public_key', field=models.CharField(blank=True, default='', max_length=80)),
        migrations.AddField(model_name='merchant', name='live_secret_hash', field=models.CharField(blank=True, default='', max_length=128)),
        migrations.AddField(model_name='merchant', name='credentials_issued_at', field=models.DateTimeField(blank=True, null=True)),
    ]