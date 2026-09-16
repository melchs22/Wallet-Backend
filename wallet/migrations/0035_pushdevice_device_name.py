from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0034_appupdatepolicy'),
    ]

    operations = [
        migrations.AddField(
            model_name='pushdevice',
            name='device_name',
            field=models.CharField(default='', max_length=120),
        ),
    ]
