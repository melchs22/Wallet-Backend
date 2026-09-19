from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0041_merchant_limits_and_team'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='public_identifier',
            field=models.SlugField(blank=True, db_index=True, max_length=80, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='merchant',
            name='logo',
            field=models.FileField(blank=True, null=True, upload_to='merchants/logos/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='merchantteammember',
            name='credentials_issued_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='providercatalog',
            name='payment_options',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
