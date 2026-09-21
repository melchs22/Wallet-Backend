# Merchant Platform Integration Testing Guide

## Overview
This guide helps you test the merchant platform with real-world integration scenarios, simulating how users would integrate the payment system into their apps.

## Prerequisites
- Django backend running at `http://178.128.156.225`
- Merchant account with ID 1 exists
- Access to Django admin panel

## Step 1: Get Your Merchant Secret Key

The merchant API requires a **secret key** (starts with `sk_live_` or `sk_test_`), not the public key.

### Option A: Via Django Admin (Recommended)
1. Go to: `http://178.128.156.225/admin/wallet/merchantapikey/2/change/`
2. Look for the secret key field
3. Copy the full secret key (it should start with `sk_live_`)

### Option B: Generate New Keys
Run the provided script:
```bash
python get_merchant_secret_key.py
```

This will:
- Show existing keys
- Offer to generate new live keys
- Display both public and secret keys

## Step 2: Configure Test Script

Edit `test_merchant_integration.sh` and replace:
```bash
MERCHANT_SECRET_KEY="YOUR_SECRET_KEY_HERE"
```

With your actual secret key:
```bash
MERCHANT_SECRET_KEY="sk_live_7JKwbeaht5-7..."
```

## Step 3: Run Integration Tests

```bash
chmod +x test_merchant_integration.sh
./test_merchant_integration.sh
```

## What Gets Tested

1. **API Authentication** - Verify secret key works
2. **Merchant Limits** - Get account limits and constraints
3. **Settings Management** - View and update merchant settings
4. **Webhook Configuration** - Set up webhook URL and events
5. **Payment Intent Creation** - Create payment requests
6. **Payment Intent Retrieval** - Get payment details
7. **Transaction Listing** - View transaction history
8. **Payment Cancellation** - Cancel pending payments

## Webhook Testing

### Option A: Use webhook.site (Easiest)
1. Go to [webhook.site](https://webhook.site)
2. Copy your unique webhook URL
3. Update merchant settings with that URL
4. Trigger a payment to see webhooks arrive

### Option B: Local Webhook Server
Use the provided webhook receiver:

```bash
python webhook_receiver.py
```

This will:
- Start a webhook server on port 5000
- Receive and verify webhook signatures
- Log all webhooks to console and `webhook_log.json`
- Provide endpoints to view received webhooks

To use it:
1. Start the webhook receiver: `python webhook_receiver.py`
2. Update merchant settings with: `http://178.128.156.225:5000/webhook`
3. Trigger a payment to see webhooks arrive
4. View received webhooks at: `http://localhost:5000/webhooks`

### Webhook Events Available
- `payment_intent.succeeded` - Payment completed successfully
- `payment_intent.failed` - Payment failed
- `payment_intent.canceled` - Payment was cancelled

### Webhook Signature Verification
Webhooks are signed with HMAC-SHA256 using your webhook secret:
```
Mi7kMWOPPeJ1659mYH6MF9gz5DHisVB3ucE0uJXe3CQ
```

Headers received:
- `X-Wallet-Signature` - HMAC signature
- `X-Wallet-Timestamp` - Unix timestamp
- `X-Wallet-Delivery-ID` - Unique delivery ID

## API Endpoints Tested

### Merchant API (merchant-api/)
- `GET /limits` - Get merchant limits
- `GET /settings` - Get merchant settings  
- `PATCH /settings` - Update merchant settings
- `POST /payment-intents` - Create payment intent
- `GET /payment-intents/:id` - Get payment intent details
- `POST /payment-intents/:id/cancel` - Cancel payment intent
- `GET /transactions` - List transactions
- `GET /transactions/:id` - Get transaction details

## Next Steps for Full Integration

1. **Complete Payment Flow**
   - Create payment intent
   - Integrate checkout confirmation in your app
   - Handle user payment completion
   - Verify webhook delivery

2. **Test Webhook Processing**
   - Set up webhook endpoint in your app
   - Implement signature verification
   - Handle different event types
   - Test retry logic for failed webhooks

3. **Test Additional Features**
   - Refunds and disputes
   - Settlements and withdrawals
   - Bank account management
   - Team member management

## Troubleshooting

### "Invalid merchant API key format"
- Ensure you're using the **secret key** (sk_live_), not public key (pk_live_)
- Check the key starts with the correct prefix
- Verify the key is active in Django admin

### "Merchant account is not active"
- Merchant must be approved for live mode
- Use sandbox mode (sk_test_) for testing if not approved

### Webhooks not received
- Verify webhook URL is publicly accessible
- Check webhook events are configured in merchant settings
- Ensure payment status actually changed (succeeded/failed/canceled)
- Check webhook delivery logs in Django admin

## Security Notes

- **Never commit secret keys** to version control
- **Rotate keys regularly** for production
- **Use webhook signature verification** to validate requests
- **Keep webhook secret secure** - it's used to sign all webhook payloads
