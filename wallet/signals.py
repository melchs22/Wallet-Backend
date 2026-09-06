import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from wallet.models import Merchant, MerchantStatus

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Merchant)
def capture_merchant_previous_status(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._previous_status = Merchant.objects.get(pk=instance.pk).status
        except Merchant.DoesNotExist:
            instance._previous_status = None
    else:
        instance._previous_status = None


@receiver(post_save, sender=Merchant)
def queue_api_keys_on_merchant_activation(sender, instance, created, **kwargs):
    previous = getattr(instance, '_previous_status', None)
    if instance.status != MerchantStatus.ACTIVE:
        return
    if previous == MerchantStatus.ACTIVE:
        return

    from wallet.tasks import generate_merchant_api_keys_task

    generate_merchant_api_keys_task.delay(instance.id)
    logger.info('merchant_activation_keys_queued', extra={'merchant_id': instance.id})
