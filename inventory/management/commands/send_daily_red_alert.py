import os
import requests
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Trigger daily RED stock alerts via Google Apps Script Web App'

    def handle(self, *args, **options):
        url = os.environ.get('GOOGLE_APPS_SCRIPT_URL')
        secret = os.environ.get('APPS_SCRIPT_SECRET')
        
        if url:
            url = url.strip().strip('"').strip("'")
        if secret:
            secret = secret.strip().strip('"').strip("'")
            
        if not url:
            self.stderr.write('Error: GOOGLE_APPS_SCRIPT_URL is not set.')
            return
        if not secret:
            self.stderr.write('Error: APPS_SCRIPT_SECRET is not set.')
            return
            
        payload = {
            "action": "send_daily_red_alert",
            "secret_token": secret
        }
        
        try:
            self.stdout.write(f'Sending daily RED alert request to Apps Script...')
            response = requests.post(url, json=payload, timeout=20)
            response.raise_for_status()
            res_data = response.json()
            if res_data.get('success'):
                self.stdout.write(self.style.SUCCESS('Successfully triggered daily RED alert email.'))
            else:
                self.stderr.write(f'Apps Script returned error: {res_data.get("error")}')
        except Exception as e:
            self.stderr.write(f'Failed to trigger daily alert: {e}')
