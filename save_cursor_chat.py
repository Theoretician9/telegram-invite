import os
import time
from datetime import datetime
import pygetwindow as gw
import pyautogui
import pyperclip

SAVE_FOLDER = "chat-logs"
INTERVAL_SECONDS = 5 * 60  # 5 минут

def save_chat():
    try:
        # Активируем окно Cursor
        win = next((w for w in gw.getWindowsWithTitle("Cursor") if w.isVisible), None)
        if not win:
            print("❌ Окно Cursor не найдено.")
            return

        win.activate()
        time.sleep(1)

        # Сфокусироваться на чате — мышь вниз вправо (на область GPT), копируем
        pyautogui.moveTo(win.left + win.width - 300, win.top + win.height - 200)
        pyautogui.click()
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.2)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(0.5)

        chat_text = pyperclip.paste()
        if not chat_text.strip():
            print("⚠️ Пустой буфер — возможно, не попал в чат.")
            return

        if not os.path.exists(SAVE_FOLDER):
            os.makedirs(SAVE_FOLDER)

        filename = f"{SAVE_FOLDER}/chat_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(chat_text)

        print(f"✅ Чат сохранён: {filename}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    print("🟢 Сохранение чата Cursor каждые 5 минут. Нажми Ctrl+C для выхода.")
    try:
        while True:
            save_chat()
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\n🛑 Остановлено вручную.")
