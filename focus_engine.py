import os
import sys
import time
import shutil
import ctypes
import threading
import sqlite3
import psutil
from datetime import datetime

# --- KONFIGURACJA (CROSS-PLATFORM) ---
if os.name == 'nt': # Windows
    HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
else: # macOS / Linux
    HOSTS_PATH = "/etc/hosts"

BACKUP_PATH = HOSTS_PATH + ".backup"
LOCK_FILE = "session.lock"
DB_FILE = "focus_stats.db"

class DatabaseManager:
    """Moduł 1: Lokalna Baza Danych (SQLite)"""
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT,
                start_time DATETIME,
                duration_minutes INTEGER,
                status TEXT
            )
        ''')
        self.conn.commit()

    def log_session(self, task, duration, status):
        self.cursor.execute(
            "INSERT INTO sessions (task_name, start_time, duration_minutes, status) VALUES (?, ?, ?, ?)",
            (task, datetime.now(), duration, status)
        )
        self.conn.commit()

class HostsBlocker:
    """Moduł 2: Bloker Sieciowy i Crash Recovery"""
    def __init__(self, blocked_sites):
        self.blocked_sites = blocked_sites

    def apply_block(self):
        # Backup pliku hosts (Zabezpieczenie)
        if not os.path.exists(BACKUP_PATH):
            shutil.copy(HOSTS_PATH, BACKUP_PATH)
        
        # Tworzenie flagi Crash Recovery
        with open(LOCK_FILE, 'w') as f:
            f.write("running")

        # Modyfikacja hosts
        with open(HOSTS_PATH, 'a') as file:
            file.write("\n# --- FOCUS MODE START ---\n")
            for site in self.blocked_sites:
                file.write(f"127.0.0.1 {site}\n")
                file.write(f"127.0.0.1 www.{site}\n")
            file.write("# --- FOCUS MODE END ---\n")

    def restore(self):
        # Przywracanie oryginału
        if os.path.exists(BACKUP_PATH):
            shutil.copy(BACKUP_PATH, HOSTS_PATH)
            os.remove(BACKUP_PATH)
        
        # Usuwanie flagi Crash Recovery
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)

    @staticmethod
    def check_crash_recovery():
        """Rozwiązanie dla zaawansowanych - sprawdza czy poprzednia sesja padła"""
        if os.path.exists(LOCK_FILE) or os.path.exists(BACKUP_PATH):
            print("[CRASH RECOVERY] Wykryto przerwaną sesję. Przywracam plik hosts...")
            if os.path.exists(BACKUP_PATH):
                shutil.copy(BACKUP_PATH, HOSTS_PATH)
                os.remove(BACKUP_PATH)
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
            print("[CRASH RECOVERY] Naprawiono pomyślnie.")

class ProcessGuard:
    """Moduł 3: Bloker Procesów (Wielowątkowość)"""
    def __init__(self, blocked_processes):
        self.blocked_processes = [p.lower() for p in blocked_processes]
        self.running = False
        self.thread = None

    def _scan_and_kill(self):
        while self.running:
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'] and proc.info['name'].lower() in self.blocked_processes:
                        print(f"[*] Strażnik ubił proces: {proc.info['name']}")
                        proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            time.sleep(3) # Optymalizacja zasobów - sprawdzanie co 3 sekundy

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._scan_and_kill, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

class FocusSession:
    """Silnik Sesji (State Machine)"""
    def __init__(self, task_name, duration_minutes, blocked_sites, blocked_processes):
        self.task_name = task_name
        self.duration_seconds = duration_minutes * 60
        self.duration_minutes = duration_minutes
        self.db = DatabaseManager()
        self.hosts = HostsBlocker(blocked_sites)
        self.guard = ProcessGuard(blocked_processes)

    def start(self):
        print(f"\n🚀 Rozpoczynam sesję: '{self.task_name}' na {self.duration_minutes} minut.")
        self.hosts.apply_block()
        self.guard.start()

        try:
            # Odliczanie (Symulacja UI / Timera)
            while self.duration_seconds > 0:
                mins, secs = divmod(self.duration_seconds, 60)
                sys.stdout.write(f"\r⏳ Pozostało: {mins:02d}:{secs:02d} (Wciśnij Ctrl+C aby przerwać)")
                sys.stdout.flush()
                time.sleep(1)
                self.duration_seconds -= 1
            
            self._end_session("SUCCESS")
            print("\n✅ Sesja zakończona sukcesem! Odblokowano system.")
            print('\a') # Odtworzenie dźwięku systemowego
            
        except KeyboardInterrupt:
            # Reakcja na przerwanie (Strict Mode)
            print("\n❌ Sesja przerwana przez użytkownika!")
            self._end_session("FAILED")

    def _end_session(self, status):
        self.guard.stop()
        self.hosts.restore()
        self.db.log_session(self.task_name, self.duration_minutes, status)

def is_admin():
    """Sprawdzenie uprawnień (Inicjalizacja)"""
    try:
        if os.name == 'nt':
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except:
        return False

# --- GŁÓWNY PRZEPŁYW (USER FLOW) ---
if __name__ == "__main__":
    if not is_admin():
        print("BŁĄD: Ta aplikacja wymaga uprawnień administratora (sudo) do edycji pliku hosts.")
        sys.exit(1)

    # 1. Sprawdzenie czy był crash systemu
    HostsBlocker.check_crash_recovery()

    # 2. Konfiguracja użytkownika
    ZABLOKOWANE_STRONY = ["facebook.com", "youtube.com", "instagram.com"]
    ZABLOKOWANE_PROCESY = ["discord.exe", "steam.exe", "discord", "steam"] # Wersje z .exe i bez (dla macOS)

    sesja = FocusSession(
        task_name="Pisanie kodu do portfolio",
        duration_minutes=1, # Ustawione na 1 minutę do szybkich testów
        blocked_sites=ZABLOKOWANE_STRONY,
        blocked_processes=ZABLOKOWANE_PROCESY
    )

    # 3. Akcja
    sesja.start()