#!/bin/bash
# Complete deployment script for PythonAnywhere
# Run this script to deploy all fixes at once

echo "=========================================="
echo "PYTHONANYWHERE DEPLOYMENT SCRIPT"
echo "=========================================="
echo ""

cd ~/Wallet-Backend

echo "Step 1: Checking current directory..."
pwd
echo ""

echo "Step 2: Activating virtual environment..."
source venv/bin/activate
echo ""

echo "Step 3: Running migrations..."
python manage.py migrate
echo ""

echo "Step 4: Collecting static files..."
python manage.py collectstatic --noinput --clear
echo ""

echo "Step 5: Running debug script to verify configuration..."
python debug_session.py
echo ""

echo "=========================================="
echo "DEPLOYMENT COMPLETE"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Check the debug script output above"
echo "2. If all settings are correct, reload the web app in PythonAnywhere dashboard"
echo "3. Test the OAuth flow"
echo ""
