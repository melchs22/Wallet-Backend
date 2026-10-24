from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('wallet', '0051_merchant_code')]
    operations = [
        migrations.AddField(
            model_name='user',
            name='language_code',
            field=models.CharField(blank=True, default='en', max_length=10),
        ),
    ]
