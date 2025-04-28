import os
import requests

# Токен бота и чат, куда будут уходить уведомления
ALERT_BOT_TOKEN = os.getenv('ALERT_BOT_TOKEN')
ALERT_CHAT_ID   = os.getenv('ALERT_CHAT_ID')

def send_alert(text: str):
    """
    Отправляет text в Telegram-чат через Bot API.
    Ничего не делает, если переменные окружения не заданы.
    """
    if not ALERT_BOT_TOKEN or not ALERT_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": ALERT_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = requests.post(url, data=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        # Если сломался сам алерт, просто выводим в лог
        print("Alert failed:", e)
