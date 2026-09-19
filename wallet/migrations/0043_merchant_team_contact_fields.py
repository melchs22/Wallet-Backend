from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0042_merchant_public_profile_and_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='merchantteammember',
            name='full_name',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='merchantteammember',
            name='phone_number',
            field=models.CharField(blank=True, default='', max_length=30),
        ),
    ]
