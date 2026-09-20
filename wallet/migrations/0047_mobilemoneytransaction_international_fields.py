from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('wallet', '0046_mobilemoneytransaction_destination_phone')]

    operations = [
        migrations.AddField(model_name='mobilemoneytransaction', name='destination_country',
                            field=models.CharField(blank=True, default='', max_length=2)),
        migrations.AddField(model_name='mobilemoneytransaction', name='receive_currency',
                            field=models.CharField(blank=True, default='', max_length=3)),
        migrations.AddField(model_name='mobilemoneytransaction', name='receive_amount',
                            field=models.DecimalField(blank=True, decimal_places=2, max_digits=20, null=True)),
        migrations.AddField(model_name='mobilemoneytransaction', name='exchange_rate',
                            field=models.DecimalField(blank=True, decimal_places=8, max_digits=20, null=True)),
    ]
