import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_email(to, subject, html):
    api_key = getattr(settings, 'RESEND_API_KEY', '')
    if not api_key:
        logger.error('RESEND_API_KEY is not configured')
        return False
    try:
        response = requests.post(
            'https://api.resend.com/emails',
            headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
            json={
                'from': getattr(settings, 'DEFAULT_FROM_EMAIL', 'DSD PAY <noreply@dsdwallet.com>'),
                'to': [to],
                'subject': subject,
                'html': html,
            },
            timeout=10,
        )
        response.raise_for_status()
        return True
    except requests.RequestException:
        logger.exception('Email delivery failed')
        return False


def branded_email(title, body, action_url=None, action_label=None):
    action = (
        f'<p><a href="{action_url}" style="display:inline-block;background:#111827;color:#fff;padding:12px 18px;border-radius:6px;text-decoration:none">{action_label}</a></p>'
        if action_url and action_label else ''
    )
    return f'''<!doctype html><html><body style="margin:0;background:#f5f5f0;padding:32px;font-family:Arial,sans-serif;color:#17212b">
    <div style="max-width:560px;margin:auto;background:#fff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden">
      <div style="background:#17212b;padding:24px;color:#fff"><img src="https://dsdwallet.com/dsd-pay-logo.png" alt="DSD PAY" width="56" height="56" style="display:block;margin-bottom:12px"><strong style="font-size:24px">DSD PAY</strong><div style="font-size:12px;letter-spacing:2px;margin-top:4px">SECURE DIGITAL PAYMENTS</div></div>
      <div style="padding:28px"><h1 style="font-size:22px">{title}</h1>{body}{action}<p style="font-size:12px;color:#6b7280">If you did not request this email, you can safely ignore it. DSD PAY will never ask for your password or private keys.</p></div>
    </div></body></html>'''
