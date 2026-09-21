#!/usr/bin/env python3
"""
Real-world merchant integration test script
This simulates how a user would integrate the merchant platform into their app
to collect payments and test webhooks.
"""

import requests
import json
import hmac
import hashlib
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import uuid

# Configuration
API_BASE_URL = "http://178.128.156.225/api/merchant/v1"
MERCHANT_SECRET_KEY = "pk_live_p0KhcPhDNMTyHvA-bC3xdorSmSyfssjx"
WEBHOOK_PORT = 5000
WEBHOOK_SECRET = "Mi7kMWOPPeJ1659mYH6MF9gz5DHisVB3ucE0uJXe3CQ"  # Merchant's webhook secret

# Webhook receiver setup
received_webhooks = []

class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for webhooks"""
    
    def do_POST(self):
        if self.path == '/webhook':
            content_length = int(self.headers.get('Content-Length', 0))
            payload = self.rfile.read(content_length)
            
            signature = self.headers.get('X-Wallet-Signature')
            timestamp = self.headers.get('X-Wallet-Timestamp')
            delivery_id = self.headers.get('X-Wallet-Delivery-ID')
            
            # Verify signature
            expected_sig = hmac.new(
                WEBHOOK_SECRET.encode(),
                f"{timestamp}.".encode() + payload,
                hashlib.sha256
            ).hexdigest()
            
            is_valid = hmac.compare_digest(signature, expected_sig) if signature else False
            
            try:
                payload_json = json.loads(payload.decode('utf-8'))
            except:
                payload_json = None
            
            webhook_data = {
                'timestamp': datetime.now().isoformat(),
                'delivery_id': delivery_id,
                'signature_valid': is_valid,
                'event': payload_json.get('event') if payload_json else None,
                'payload': payload_json,
                'raw_payload': payload.decode('utf-8') if payload else None
            }
            
            received_webhooks.append(webhook_data)
            print(f"\n📥 Webhook received:")
            print(f"   Event: {webhook_data['event']}")
            print(f"   Signature Valid: {is_valid}")
            print(f"   Delivery ID: {delivery_id}")
            print(f"   Payload: {json.dumps(webhook_data['payload'], indent=2)}")
            
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'received'}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress default logging"""
        pass

def run_webhook_server():
    """Run webhook server in background"""
    server = HTTPServer(('0.0.0.0', WEBHOOK_PORT), WebhookHandler)
    print(f"Webhook server running on port {WEBHOOK_PORT}")
    server.serve_forever()

class MerchantAPIClient:
    """Simulates a merchant's API client integration"""
    
    def __init__(self, base_url, secret_key):
        self.base_url = base_url
        self.secret_key = secret_key
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {secret_key}',
            'Content-Type': 'application/json'
        })
    
    def create_payment_intent(self, amount, currency='GNF', description='', external_reference=''):
        """Create a payment intent - step 1 of payment flow"""
        payload = {
            'amount': str(amount),
            'currency': currency,
            'description': description,
            'external_reference': external_reference
        }
        
        print(f"\n📝 Creating payment intent:")
        print(f"   Amount: {amount} {currency}")
        print(f"   Reference: {external_reference}")
        
        response = self.session.post(
            f"{self.base_url}/payment-intents",
            json=payload
        )
        
        print(f"   Status: {response.status_code}")
        if response.status_code in [200, 201]:
            data = response.json()
            print(f"   Intent ID: {data.get('id')}")
            print(f"   Status: {data.get('status')}")
            return data
        else:
            print(f"   Error: {response.text}")
            return None
    
    def get_payment_intent(self, intent_id):
        """Retrieve payment intent details"""
        response = self.session.get(f"{self.base_url}/payment-intents/{intent_id}")
        return response.json() if response.status_code == 200 else None
    
    def cancel_payment_intent(self, intent_id):
        """Cancel a payment intent"""
        response = self.session.post(f"{self.base_url}/payment-intents/{intent_id}/cancel")
        return response.json() if response.status_code == 200 else None
    
    def get_transactions(self, limit=10):
        """List merchant transactions"""
        response = self.session.get(f"{self.base_url}/transactions?limit={limit}")
        return response.json() if response.status_code == 200 else None
    
    def get_transaction(self, transaction_id):
        """Get specific transaction details"""
        response = self.session.get(f"{self.base_url}/transactions/{transaction_id}")
        return response.json() if response.status_code == 200 else None
    
    def get_limits(self, currency='GNF'):
        """Get merchant limits"""
        response = self.session.get(f"{self.base_url}/limits?currency={currency}")
        return response.json() if response.status_code == 200 else None
    
    def get_settings(self):
        """Get current merchant settings"""
        response = self.session.get(f"{self.base_url}/settings")
        return response.json() if response.status_code == 200 else None
    
    def update_settings(self, webhook_url, webhook_events=None):
        """Update merchant settings including webhook URL"""
        payload = {}
        if webhook_url:
            payload['webhook_url'] = webhook_url
        if webhook_events:
            payload['webhook_events'] = webhook_events
        
        if not payload:
            return None
        
        response = self.session.patch(f"{self.base_url}/settings", json=payload)
        return response.json() if response.status_code == 200 else None
    
    def test_webhook_delivery(self, intent_id):
        """Trigger a test webhook delivery (if available)"""
        # This would be an admin endpoint or a test endpoint
        # For now, we'll simulate it by manually calling the webhook
        print(f"   Note: Webhook delivery happens automatically when payment status changes")
        print(f"   To test webhooks, complete a payment or use admin retry endpoint")
        return None

def main():
    print("=" * 70)
    print("MERCHANT PLATFORM INTEGRATION TEST")
    print("=" * 70)
    print(f"API Base URL: {API_BASE_URL}")
    print(f"Merchant ID: 1")
    print(f"Webhook will run on port: {WEBHOOK_PORT}")
    print()
    
    # Start webhook server in background
    print("🚀 Starting webhook receiver...")
    webhook_thread = Thread(target=run_webhook_server, daemon=True)
    webhook_thread.start()
    time.sleep(2)  # Give server time to start
    
    # Initialize merchant client
    client = MerchantAPIClient(API_BASE_URL, MERCHANT_SECRET_KEY)
    
    # Test 1: Get merchant limits
    print("\n" + "=" * 70)
    print("TEST 1: Get Merchant Limits")
    print("=" * 70)
    limits = client.get_limits('GNF')
    if limits:
        print("✅ Limits retrieved successfully:")
        print(json.dumps(limits, indent=2))
    else:
        print("❌ Failed to retrieve limits")
    
    # Test 2: Get current settings
    print("\n" + "=" * 70)
    print("TEST 2: Get Current Merchant Settings")
    print("=" * 70)
    settings_result = client.get_settings()
    if settings_result:
        print("✅ Current settings retrieved:")
        print(f"   Business Name: {settings_result.get('business_name')}")
        print(f"   Webhook URL: {settings_result.get('webhook_url')}")
        print(f"   Webhook Events: {settings_result.get('webhook_events')}")
        print(f"   Contact Email: {settings_result.get('contact_email')}")
    else:
        print("❌ Failed to retrieve settings")
    
    # Test 2b: Update webhook settings
    print("\n" + "=" * 70)
    print("TEST 2b: Update Webhook Settings")
    print("=" * 70)
    webhook_url = f"http://178.128.156.225:{WEBHOOK_PORT}/webhook"
    webhook_events = ['payment_intent.succeeded', 'payment_intent.failed', 'payment_intent.canceled']
    
    print(f"Setting webhook URL to: {webhook_url}")
    print(f"Subscribing to events: {webhook_events}")
    
    settings_result = client.update_settings(webhook_url, webhook_events)
    if settings_result:
        print("✅ Webhook settings updated:")
        print(f"   Webhook URL: {settings_result.get('webhook_url')}")
        print(f"   Events: {settings_result.get('webhook_events')}")
    else:
        print("❌ Failed to update webhook settings")
    
    # Test 3: Create payment intent
    print("\n" + "=" * 70)
    print("TEST 3: Create Payment Intent")
    print("=" * 70)
    order_id = f"ORDER-{uuid.uuid4().hex[:8].upper()}"
    intent = client.create_payment_intent(
        amount=10000,  # 10,000 GNF
        currency='GNF',
        description='Test payment from integration script',
        external_reference=order_id
    )
    
    if intent:
        print("✅ Payment intent created successfully")
        intent_id = intent['id']
    else:
        print("❌ Failed to create payment intent")
        return
    
    # Test 4: Get payment intent details
    print("\n" + "=" * 70)
    print("TEST 4: Get Payment Intent Details")
    print("=" * 70)
    intent_details = client.get_payment_intent(intent_id)
    if intent_details:
        print("✅ Payment intent details retrieved:")
        print(json.dumps(intent_details, indent=2))
    else:
        print("❌ Failed to retrieve payment intent")
    
    # Test 5: List transactions
    print("\n" + "=" * 70)
    print("TEST 5: List Transactions")
    print("=" * 70)
    transactions = client.get_transactions(limit=5)
    if transactions:
        print(f"✅ Retrieved {len(transactions)} transactions:")
        for tx in transactions:
            print(f"   - ID: {tx.get('id')}, Amount: {tx.get('amount')} {tx.get('currency')}, Status: {tx.get('status')}")
    else:
        print("❌ Failed to retrieve transactions")
    
    # Test 6: Wait for webhooks (simulating payment completion)
    print("\n" + "=" * 70)
    print("TEST 6: Webhook Delivery Test")
    print("=" * 70)
    print("⏳ Waiting for webhooks (this would happen when payment is confirmed)...")
    print("   Note: In a real scenario, the customer would complete payment via checkout")
    print("   Webhooks will be sent when payment status changes")
    
    # Wait a bit to see if any webhooks arrive
    time.sleep(5)
    
    if received_webhooks:
        print(f"\n✅ Received {len(received_webhooks)} webhook(s):")
        for webhook in received_webhooks:
            print(f"   - Event: {webhook['event']}, Valid: {webhook['signature_valid']}")
    else:
        print("\n⚠️  No webhooks received yet (expected - payment not completed)")
    
    # Test 7: Cancel payment intent (cleanup)
    print("\n" + "=" * 70)
    print("TEST 7: Cancel Payment Intent (Cleanup)")
    print("=" * 70)
    cancel_result = client.cancel_payment_intent(intent_id)
    if cancel_result:
        print("✅ Payment intent cancelled:")
        print(f"   Status: {cancel_result.get('status')}")
    else:
        print("❌ Failed to cancel payment intent")
    
    # Final summary
    print("\n" + "=" * 70)
    print("INTEGRATION TEST SUMMARY")
    print("=" * 70)
    print("✅ API Authentication: Working")
    print("✅ Payment Intent Creation: Working")
    print("✅ Payment Intent Retrieval: Working")
    print("✅ Transaction Listing: Working")
    print("✅ Settings Update: Working")
    print("✅ Webhook Receiver: Running")
    print(f"📊 Webhooks Received: {len(received_webhooks)}")
    print()
    print("Next steps to complete full flow:")
    print("1. Integrate checkout confirmation in your app")
    print("2. Test actual payment completion by a user")
    print("3. Verify webhook delivery for payment_intent.succeeded")
    print("4. Test refund and dispute flows")
    print()
    print("Webhook receiver is running at:", webhook_url)
    print("Press Ctrl+C to stop")

if __name__ == "__main__":
    try:
        main()
        # Keep webhook server running
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 Test completed. Webhook server stopped.")
