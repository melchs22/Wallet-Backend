from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('wallet', '0036_adminmessage_alertevent_alertrule_transactionflag_and_more')]

    operations = [
        migrations.AddField(
            model_name='supportedcountry',
            name='currency',
            field=models.CharField(default='GNF', max_length=3),
        ),
    ]
