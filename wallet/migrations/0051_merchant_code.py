from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0050_merchantapikey_secret_encrypted'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchant',
            name='merchant_code',
            field=models.CharField(blank=True, db_index=True, max_length=6, null=True, unique=True),
        ),
    ]
