from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0033_pending_login_requests_and_device_keys'),
    ]

    operations = [
        migrations.CreateModel(
            name='AppUpdatePolicy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('platform', models.CharField(choices=[('ios', 'iOS'), ('android', 'Android')], max_length=10, unique=True)),
                ('minimum_version', models.CharField(default='1.0.0', max_length=30)),
                ('update_url', models.URLField(max_length=500)),
                ('enabled', models.BooleanField(default=False)),
                ('title', models.CharField(default='Update required', max_length=120)),
                ('message', models.TextField(default='Please update the app to continue.')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'app_update_policies',
                'ordering': ['platform'],
            },
        ),
    ]
