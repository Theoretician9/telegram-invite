import time
import subprocess
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCHED_EXTENSIONS = ['.py', '.js', '.ts', '.json', '.env', '.sh', '.txt', '.md']
HAS_CHANGES = False
CHECK_INTERVAL = 30  # секунд

class AutoGitHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        global HAS_CHANGES
        if not event.is_directory and Path(event.src_path).suffix in WATCHED_EXTENSIONS:
            HAS_CHANGES = True
            print(f"🟡 Изменено: {event.src_path}")

def run_git_commit():
    try:
        subprocess.call(['git', 'add', '--all'])
        subprocess.call(['git', 'commit', '-m', 'Auto-commit every 30s'])
        # push выполнится автоматически через post-commit хук
        print("✅ Изменения запушены")
    except Exception as e:
        print(f"❌ Ошибка при коммите: {e}")

if __name__ == "__main__":
    print("🟢 Старт слежения. Каждые 30 секунд — коммит и пуш, если были изменения.")
    observer = Observer()
    event_handler = AutoGitHandler()
    observer.schedule(event_handler, path='.', recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(CHECK_INTERVAL)
            if HAS_CHANGES:
                run_git_commit()
                HAS_CHANGES = False
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
