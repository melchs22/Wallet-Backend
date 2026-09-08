from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0016_gnf_default_currency'),
    ]

    operations = [
        migrations.AlterField(
            model_name='merchant',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('active', 'Active'),
                    ('suspended', 'Suspended'),
                    ('rejected', 'Rejected'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
