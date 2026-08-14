#!/bin/bash
# Script to collect static files for Django deployment

echo "Collecting static files..."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Collect static files
python manage.py collectstatic --noinput --clear

echo "Static files collected successfully!"
echo "Files are in: staticfiles/"
