from telethon.sync import TelegramClient

api_id = 25966514        # например 1234567
api_hash = '02f2aadfe27c0e407856c371c111630d'  # например '0123456789abcdef0123456789abcdef'
session_name = 'invite_session'

# Создаём клиент и запускаем авторизацию
client = TelegramClient(session_name, api_id, api_hash)
client.start()  # попросит номер и код из Telegram

print("✅ Сессия успешно сохранена в файле:", session_name + ".session")
client.disconnect()
