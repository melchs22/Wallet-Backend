#!/usr/bin/env python
"""
Script to reveal merchant secret key
Run this from the Django project root: python get_merchant_secret_key.py
"""

import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'walletmvp.settings')
django.setup()

from wallet.models import MerchantApiKey, Merchant
from wallet.services.merchants import generate_merchant_api_keys
from wallet.models import MerchantMode

def reveal_or_generate_keys():
    """Reveal existing secret key or generate new ones"""
    
    # Get merchant with ID 1
    try:
        merchant = Merchant.objects.get(id=1)
        print(f"Found merchant: {merchant.business_name}")
    except Merchant.DoesNotExist:
        print("❌ Merchant with ID 1 not found")
        return
    
    # Check for existing live keys
    live_keys = MerchantApiKey.objects.filter(merchant=merchant, mode=MerchantMode.LIVE, is_active=True)
    
    if live_keys.exists():
        print(f"\n📋 Found {live_keys.count()} existing live API key(s):")
        for key in live_keys:
            print(f"\n   Key ID: {key.id}")
            print(f"   Public Key: {key.public_key}")
            print(f"   Secret Key Prefix: {key.secret_key_prefix}")
            print(f"   Mode: {key.mode}")
            print(f"   Active: {key.is_active}")
            print(f"   Created: {key.created_at}")
            print(f"   ⚠️  Note: The full secret key is hashed in the database.")
            print(f"   ⚠️  To get the full secret key, you need to:")
            print(f"      1. Go to Django admin: http://178.128.156.225/admin/wallet/merchantapikey/{key.id}/change/")
            print(f"      2. Or generate new keys (see below)")
    
    # Ask if user wants to generate new keys
    print("\n" + "="*70)
    print("GENERATE NEW API KEYS")
    print("="*70)
    print("⚠️  WARNING: Generating new keys will invalidate any existing keys.")
    print("Do you want to generate new live API keys? (yes/no): ", end="")
    
    response = input().strip().lower()
    if response not in ['yes', 'y']:
        print("Cancelled. No new keys generated.")
        return
    
    # Generate new keys
    print("\n🔑 Generating new live API keys...")
    public_key, secret_key = generate_merchant_api_keys(merchant, MerchantMode.LIVE)
    
    print("\n✅ New API keys generated successfully!")
    print(f"\n   Public Key: {public_key}")
    print(f"   Secret Key: {secret_key}")
    print(f"\n⚠️  IMPORTANT: Save the secret key securely!")
    print(f"   You won't be able to see it again after this.")
    print(f"\n📝 Update your test script with:")
    print(f"   MERCHANT_SECRET_KEY=\"{secret_key}\"")

if __name__ == "__main__":
    reveal_or_generate_keys()
