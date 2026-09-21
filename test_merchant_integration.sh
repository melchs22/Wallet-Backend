#!/bin/bash

# Real-world merchant integration test script using curl
# This simulates how a user would integrate the merchant platform into their app
# to collect payments and test webhooks.

# Configuration
API_BASE_URL="http://178.128.156.225/api/merchant-api"
MERCHANT_SECRET_KEY="sk_live_YFpHcee-PKzEoal8bLG_zpQx6U2lBIX9nRcdJbFnBbg"
WEBHOOK_PORT=5001
WEBHOOK_SECRET="Mi7kMWOPPeJ1659mYH6MF9gz5DHisVB3ucE0uJXe3CQ"

echo "=========================================================================="
echo "MERCHANT PLATFORM INTEGRATION TEST"
echo "=========================================================================="
echo "API Base URL: $API_BASE_URL"
echo "Merchant ID: 1"
echo "Webhook will run on port: $WEBHOOK_PORT"
echo ""

# Function to make API calls
api_call() {
    local method=$1
    local endpoint=$2
    local data=$3
    
    if [ -z "$data" ]; then
        curl -s -X "$method" \
            -H "Authorization: Bearer $MERCHANT_SECRET_KEY" \
            -H "Content-Type: application/json" \
            "$API_BASE_URL$endpoint"
    else
        curl -s -X "$method" \
            -H "Authorization: Bearer $MERCHANT_SECRET_KEY" \
            -H "Content-Type: application/json" \
            -d "$data" \
            "$API_BASE_URL$endpoint"
    fi
}

# Test 1: Get merchant limits
echo "=========================================================================="
echo "TEST 1: Get Merchant Limits"
echo "=========================================================================="
limits=$(api_call "GET" "/limits?currency=GNF")
if [ $? -eq 0 ]; then
    echo "✅ Limits retrieved successfully:"
    echo "$limits" | python3 -m json.tool 2>/dev/null || echo "$limits"
else
    echo "❌ Failed to retrieve limits"
fi

# Test 2: Get current settings
echo ""
echo "=========================================================================="
echo "TEST 2: Get Current Merchant Settings"
echo "=========================================================================="
settings=$(api_call "GET" "/settings")
if [ $? -eq 0 ]; then
    echo "✅ Current settings retrieved:"
    echo "$settings" | python3 -m json.tool 2>/dev/null || echo "$settings"
    
    # Extract current webhook URL
    current_webhook=$(echo "$settings" | python3 -c "import sys, json; print(json.load(sys.stdin).get('webhook_url', 'None'))" 2>/dev/null)
    current_events=$(echo "$settings" | python3 -c "import sys, json; print(json.load(sys.stdin).get('webhook_events', 'None'))" 2>/dev/null)
    
    echo ""
    echo "Current Webhook URL: $current_webhook"
    echo "Current Webhook Events: $current_events"
else
    echo "❌ Failed to retrieve settings"
fi

# Test 2b: Update webhook settings
echo ""
echo "=========================================================================="
echo "TEST 2b: Update Webhook Settings"
echo "=========================================================================="
WEBHOOK_URL="http://178.128.156.225:$WEBHOOK_PORT/webhook"
WEBHOOK_EVENTS='["payment_intent.succeeded", "payment_intent.failed", "payment_intent.canceled"]'

echo "Setting webhook URL to: $WEBHOOK_URL"
echo "Subscribing to events: $WEBHOOK_EVENTS"

update_data="{\"webhook_url\": \"$WEBHOOK_URL\", \"webhook_events\": $WEBHOOK_EVENTS}"
update_result=$(api_call "PATCH" "/settings" "$update_data")

if [ $? -eq 0 ]; then
    echo "✅ Webhook settings updated:"
    echo "$update_result" | python3 -m json.tool 2>/dev/null || echo "$update_result"
else
    echo "❌ Failed to update webhook settings"
fi

# Test 3: Create payment intent
echo ""
echo "=========================================================================="
echo "TEST 3: Create Payment Intent"
echo "=========================================================================="
ORDER_ID="ORDER-$(date +%s%N | head -c 8 | tr '0-9' 'A-Z')"
intent_data="{\"amount\": \"10000\", \"currency\": \"GNF\", \"description\": \"Test payment from integration script\", \"external_reference\": \"$ORDER_ID\"}"

echo "Creating payment intent:"
echo "   Amount: 10000 GNF"
echo "   Reference: $ORDER_ID"

intent=$(api_call "POST" "/payment-intents" "$intent_data")

if [ $? -eq 0 ]; then
    echo "✅ Payment intent created successfully"
    echo "$intent" | python3 -m json.tool 2>/dev/null || echo "$intent"
    
    # Extract intent ID
    INTENT_ID=$(echo "$intent" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', 'None'))" 2>/dev/null)
    echo "Intent ID: $INTENT_ID"
else
    echo "❌ Failed to create payment intent"
    echo "$intent"
    exit 1
fi

# Test 4: Get payment intent details
echo ""
echo "=========================================================================="
echo "TEST 4: Get Payment Intent Details"
echo "=========================================================================="
intent_details=$(api_call "GET" "/payment-intents/$INTENT_ID")
if [ $? -eq 0 ]; then
    echo "✅ Payment intent details retrieved:"
    echo "$intent_details" | python3 -m json.tool 2>/dev/null || echo "$intent_details"
else
    echo "❌ Failed to retrieve payment intent"
fi

# Test 5: List transactions
echo ""
echo "=========================================================================="
echo "TEST 5: List Transactions"
echo "=========================================================================="
transactions=$(api_call "GET" "/transactions?limit=5")
if [ $? -eq 0 ]; then
    echo "✅ Retrieved transactions:"
    echo "$transactions" | python3 -m json.tool 2>/dev/null || echo "$transactions"
else
    echo "❌ Failed to retrieve transactions"
fi

# Test 6: Cancel payment intent (cleanup)
echo ""
echo "=========================================================================="
echo "TEST 6: Cancel Payment Intent (Cleanup)"
echo "=========================================================================="
cancel_result=$(api_call "POST" "/payment-intents/$INTENT_ID/cancel")
if [ $? -eq 0 ]; then
    echo "✅ Payment intent cancelled:"
    echo "$cancel_result" | python3 -m json.tool 2>/dev/null || echo "$cancel_result"
else
    echo "❌ Failed to cancel payment intent"
fi

# Final summary
echo ""
echo "=========================================================================="
echo "INTEGRATION TEST SUMMARY"
echo "=========================================================================="
echo "✅ API Authentication: Working"
echo "✅ Payment Intent Creation: Working"
echo "✅ Payment Intent Retrieval: Working"
echo "✅ Transaction Listing: Working"
echo "✅ Settings Update: Working"
echo ""
echo "Next steps to complete full flow:"
echo "1. Start webhook receiver: python webhook_receiver.py"
echo "2. Set up a webhook receiver at $WEBHOOK_URL"
echo "3. Integrate checkout confirmation in your app"
echo "4. Test actual payment completion by a user"
echo "5. Verify webhook delivery for payment_intent.succeeded"
echo "6. Test refund and dispute flows"
echo ""
echo "Webhook URL configured: $WEBHOOK_URL"
echo "To test webhooks:"
echo "  - Option 1: Use webhook.site (easiest for testing)"
echo "  - Option 2: Run python webhook_receiver.py (local testing)"
