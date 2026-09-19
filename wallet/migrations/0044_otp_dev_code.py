from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0043_merchant_team_contact_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='otpchallenge',
            name='dev_code',
            field=models.CharField(blank=True, default='', max_length=6),
        ),
    ]
