from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0017_alter_merchant_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='limits_manually_set',
            field=models.BooleanField(default=False),
        ),
    ]
