import time
import subprocess
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

WATCHED_EXTENSIONS = ['.py', '.js', '.ts', '.json', '.env', '.sh', '.txt', '.md']

class AutoGitHandler(FileSystemEventHandler):
    def on_any_event(self, event):
        if not event.is_directory and Path(event.src_path).suffix in WATCHED_EXTENSIONS:
            print(f"Изменено: {event.src_path}")
            subprocess.call(['git', 'add', '--all'])
            subprocess.call(['git', 'commit', '-m', 'Auto-commit on save'])
            # git push делается хуком post-commit

if __name__ == "__main__":
    path = "."
    event_handler = AutoGitHandler()
    observer = Observer()
    observer.schedule(event_handler, path=path, recursive=True)
    observer.start()
    print("Слежу за изменениями. Нажми Ctrl+C для выхода.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
