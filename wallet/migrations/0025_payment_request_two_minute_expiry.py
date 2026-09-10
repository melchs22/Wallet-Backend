from datetime import timedelta

from django.db import migrations, models
from django.utils import timezone
import wallet.models


def expire_existing_requests(apps, schema_editor):
    PaymentRequest = apps.get_model('wallet', 'PaymentRequest')
    now = timezone.now()
    pending_requests = PaymentRequest.objects.filter(status='pending')
    for payment_request in pending_requests.iterator():
        payment_request.expires_at = payment_request.created_at + timedelta(minutes=2)
        if payment_request.expires_at <= now:
            payment_request.status = 'expired'
        payment_request.save(update_fields=['expires_at', 'status'])


class Migration(migrations.Migration):
    dependencies = [
        ('wallet', '0024_expand_transaction_pin'),
    ]

    operations = [
        migrations.RunPython(expire_existing_requests, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='paymentrequest',
            name='expires_at',
            field=models.DateTimeField(default=wallet.models.default_request_expiry),
        ),
    ]