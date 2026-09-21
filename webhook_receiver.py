#!/usr/bin/env python3
"""
Simple webhook receiver for testing merchant webhooks
This receives webhook events and logs them for verification
"""

import json
import hmac
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
import threading
import time

# Configuration
WEBHOOK_PORT = 5000
WEBHOOK_SECRET = "Mi7kMWOPPeJ1659mYH6MF9gz5DHisVB3ucE0uJXe3CQ"  # Your merchant's webhook secret

# Store received webhooks
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
            
            # Log to console
            print(f"\n{'='*70}")
            print(f"📥 WEBHOOK RECEIVED")
            print(f"{'='*70}")
            print(f"Time: {webhook_data['timestamp']}")
            print(f"Event: {webhook_data['event']}")
            print(f"Delivery ID: {delivery_id}")
            print(f"Signature Valid: {is_valid}")
            print(f"Timestamp: {timestamp}")
            print(f"\nPayload:")
            print(json.dumps(webhook_data['payload'], indent=2))
            print(f"{'='*70}\n")
            
            # Save to file
            with open('webhook_log.json', 'a') as f:
                f.write(json.dumps(webhook_data, indent=2) + '\n')
            
            # Return success response
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'received'}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_GET(self):
        if self.path == '/webhooks':
            """Return list of received webhooks"""
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(received_webhooks, indent=2).encode())
        elif self.path == '/health':
            """Health check endpoint"""
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'healthy', 'webhooks_received': len(received_webhooks)}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress default HTTP logging"""
        pass

def main():
    print(f"🚀 Webhook receiver starting on port {WEBHOOK_PORT}")
    print(f"📡 Webhook endpoint: http://localhost:{WEBHOOK_PORT}/webhook")
    print(f"🔍 View received webhooks: http://localhost:{WEBHOOK_PORT}/webhooks")
    print(f"❤️  Health check: http://localhost:{WEBHOOK_PORT}/health")
    print(f"🔑 Using webhook secret: {WEBHOOK_SECRET[:20]}...")
    print(f"\n⚠️  Make sure your merchant settings point to:")
    print(f"   http://178.128.156.225:{WEBHOOK_PORT}/webhook")
    print(f"\nPress Ctrl+C to stop\n")
    
    server = HTTPServer(('0.0.0.0', WEBHOOK_PORT), WebhookHandler)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Webhook receiver stopped")
        print(f"📊 Total webhooks received: {len(received_webhooks)}")
        print(f"📁 Webhooks logged to: webhook_log.json")

if __name__ == "__main__":
    main()
