from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('wallet', '0047_mobilemoneytransaction_international_fields')]

    operations = [
        migrations.AddField(
            model_name='pushdevice',
            name='language_code',
            field=models.CharField(blank=True, default='fr', max_length=10),
        ),
    ]
