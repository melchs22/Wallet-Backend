from django.urls import path

from . import merchant_views

urlpatterns = [
    path('payment-intents', merchant_views.merchant_create_payment_intent, name='merchant_create_payment_intent'),
    path('limits', merchant_views.merchant_limits, name='merchant_limits'),
    path('payment-intents/<int:intent_id>', merchant_views.merchant_get_payment_intent, name='merchant_get_payment_intent'),
    path('payment-intents/<int:intent_id>/cancel', merchant_views.merchant_cancel_payment_intent, name='merchant_cancel_payment_intent'),
    path('transactions', merchant_views.merchant_transactions, name='merchant_transactions'),
    path('transactions/<str:transaction_id>', merchant_views.merchant_transaction_detail, name='merchant_transaction_detail'),
    path('settlements', merchant_views.merchant_settlements, name='merchant_settlements'),
    path('settings', merchant_views.merchant_settings, name='merchant_settings'),
    path('disputes', merchant_views.merchant_disputes, name='merchant_disputes'),
    path('disputes/<int:dispute_id>', merchant_views.merchant_dispute_detail, name='merchant_dispute_detail'),
    path('refunds', merchant_views.merchant_refund, name='merchant_refund'),
    path('webhooks/<int:delivery_id>/retry', merchant_views.merchant_webhook_retry, name='merchant_webhook_retry'),
]
