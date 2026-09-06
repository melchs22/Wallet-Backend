from django.urls import path

from . import merchant_views

urlpatterns = [
    path('payment-intents', merchant_views.merchant_create_payment_intent, name='merchant_create_payment_intent'),
    path('payment-intents/<int:intent_id>', merchant_views.merchant_get_payment_intent, name='merchant_get_payment_intent'),
    path('payment-intents/<int:intent_id>/cancel', merchant_views.merchant_cancel_payment_intent, name='merchant_cancel_payment_intent'),
]
