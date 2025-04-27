# alerts.py
import os
import requests

BOT_TOKEN = os.getenv('ALERT_BOT_TOKEN')
CHAT_ID   = os.getenv('ALERT_CHAT_ID')

def send_alert(text: str):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, json={
        'chat_id': CHAT_ID,
        'text': text
    })
