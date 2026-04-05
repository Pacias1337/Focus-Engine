import os
import sys
import time
import shutil
import ctypes
import threading
import sqlite3
import psutil
from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox

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

class FocusApp:
    """Główna aplikacja z Interfejsem Graficznym (UI)"""
    def __init__(self, root):
        self.root = root
        self.root.title("Focus Mode - Zbuduj Skupienie")
        self.root.geometry("400x350")
        self.root.configure(bg="#f4f4f9")
        self.root.resizable(False, False)

        # Inicjalizacja modułów backendowych
        self.db = DatabaseManager()
        ZABLOKOWANE_STRONY = ["facebook.com", "youtube.com", "instagram.com"]
        ZABLOKOWANE_PROCESY = ["discord.exe", "steam.exe", "discord", "steam"]
        
        self.hosts = HostsBlocker(ZABLOKOWANE_STRONY)
        self.guard = ProcessGuard(ZABLOKOWANE_PROCESY)

        self.time_left = 0
        self.is_running = False
        self.duration_minutes = 0
        self.task_name = ""

        self.setup_ui()
        
        # Zabezpieczenie przed zamknięciem okna "igreksem" w trakcie sesji
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_ui(self):
        """Tworzy elementy interfejsu użytkownika"""
        style = ttk.Style()
        style.configure("TLabel", background="#f4f4f9", font=("Helvetica", 12))
        style.configure("TButton", font=("Helvetica", 12, "bold"))

        # Kontener główny
        self.main_frame = tk.Frame(self.root, bg="#f4f4f9", padx=20, pady=20)
        self.main_frame.pack(expand=True, fill=tk.BOTH)

        # Tytuł
        title_label = tk.Label(self.main_frame, text="Zacznij Sesję Pracy", font=("Helvetica", 18, "bold"), bg="#f4f4f9", fg="#333")
        title_label.pack(pady=(0, 20))

        # Pole zadania
        tk.Label(self.main_frame, text="Co będziesz robić?", font=("Helvetica", 10), bg="#f4f4f9").pack(anchor="w")
        self.task_entry = ttk.Entry(self.main_frame, width=30, font=("Helvetica", 12))
        self.task_entry.pack(fill=tk.X, pady=(0, 15))
        self.task_entry.insert(0, "Praca nad kodem")

        # Pole czasu
        tk.Label(self.main_frame, text="Czas trwania (minuty):", font=("Helvetica", 10), bg="#f4f4f9").pack(anchor="w")
        self.time_entry = ttk.Spinbox(self.main_frame, from_=1, to=120, width=5, font=("Helvetica", 12))
        self.time_entry.pack(anchor="w", pady=(0, 25))
        self.time_entry.set(25) # Domyślnie 25 minut (Pomodoro)

        # Timer (Ukryty na starcie)
        self.timer_label = tk.Label(self.main_frame, text="00:00", font=("Helvetica", 48, "bold"), bg="#f4f4f9", fg="#d32f2f")

        # Przycisk Start
        self.start_btn = tk.Button(self.main_frame, text="ROZPOCZNIJ", bg="#4CAF50", fg="white", font=("Helvetica", 12, "bold"), pady=10, command=self.start_session)
        self.start_btn.pack(fill=tk.X)
        
        # Przycisk Przerwij (Ukryty na starcie)
        self.stop_btn = tk.Button(self.main_frame, text="PODDAJĘ SIĘ (PRZERWIJ)", bg="#f44336", fg="white", font=("Helvetica", 10, "bold"), pady=5, command=self.stop_session)

    def start_session(self):
        """Rozpoczyna blokowanie i odliczanie"""
        task = self.task_entry.get().strip()
        try:
            mins = int(self.time_entry.get())
        except ValueError:
            messagebox.showerror("Błąd", "Czas musi być liczbą!")
            return

        if not task or mins <= 0:
            messagebox.showerror("Błąd", "Wprowadź poprawne dane.")
            return

        self.task_name = task
        self.duration_minutes = mins
        self.time_left = mins * 60
        self.is_running = True

        # Rozpoczęcie blokad
        self.hosts.apply_block()
        self.guard.start()

        # Zmiana UI (ukrywanie formularza, pokazywanie timera)
        self.task_entry.pack_forget()
        self.time_entry.pack_forget()
        self.start_btn.pack_forget()
        for widget in self.main_frame.winfo_children():
            if isinstance(widget, tk.Label) and widget.cget("text") in ["Co będziesz robić?", "Czas trwania (minuty):"]:
                widget.pack_forget()

        self.timer_label.pack(pady=20)
        self.stop_btn.pack(fill=tk.X, pady=(10, 0))

        # Start pętli odliczania UI
        self.update_timer()

    def update_timer(self):
        """Asynchroniczne odświeżanie timera w UI"""
        if self.is_running and self.time_left > 0:
            mins, secs = divmod(self.time_left, 60)
            self.timer_label.config(text=f"{mins:02d}:{secs:02d}")
            self.time_left -= 1
            # Powtarzaj funkcję co 1000 ms (1 sekunda) bez blokowania okna
            self.root.after(1000, self.update_timer)
        elif self.is_running and self.time_left <= 0:
            self.finish_session("SUCCESS")

    def finish_session(self, status):
        """Zakończenie z sukcesem"""
        self.is_running = False
        self.guard.stop()
        self.hosts.restore()
        self.db.log_session(self.task_name, self.duration_minutes, status)
        
        if status == "SUCCESS":
            print('\a') # Dźwięk systemowy
            messagebox.showinfo("Koniec!", "Świetna robota! Sesja zakończona sukcesem.\nInternet i aplikacje odblokowane.")
        
        self.reset_ui()

    def stop_session(self):
        """Poddanie się przez użytkownika (Strict mode z ostrzeżeniem)"""
        if messagebox.askyesno("Ostrzeżenie", "Czy na pewno chcesz przerwać? Zepsuje to Twoje statystyki w bazie danych!"):
            self.is_running = False
            self.guard.stop()
            self.hosts.restore()
            self.db.log_session(self.task_name, self.duration_minutes, "FAILED")
            messagebox.showwarning("Przerwano", "Sesja przerwana. System odblokowany, ale zadanie oznaczono jako nieukończone.")
            self.reset_ui()

    def reset_ui(self):
        """Przywraca UI do stanu początkowego"""
        self.timer_label.pack_forget()
        self.stop_btn.pack_forget()
        
        # Odtworzenie wszystkich elementów interfejsu (prosty restart okna)
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        self.setup_ui()

    def on_closing(self):
        """Blokada zamknięcia okna "igreksem" jeśli trwa sesja"""
        if self.is_running:
            messagebox.showwarning("Blokada", "Trwa sesja Focus Mode! Użyj przycisku 'Przerwij', jeśli musisz wyjść.")
        else:
            self.root.destroy()

def is_admin():
    """Sprawdzenie uprawnień (Inicjalizacja)"""
    try:
        if os.name == 'nt':
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except:
        return False

# --- GŁÓWNY PRZEPŁYW ---
if __name__ == "__main__":
    if not is_admin():
        print("BŁĄD: Ta aplikacja wymaga uprawnień administratora (sudo) do edycji pliku hosts.")
        sys.exit(1)

    # 1. Sprawdzenie czy był crash systemu
    HostsBlocker.check_crash_recovery()

    # 2. Uruchomienie interfejsu graficznego (UI)
    root = tk.Tk()
    app = FocusApp(root)
    
    # Przechwytywanie Ctrl+C w terminalu, żeby mimo to oczyścić hosts
    try:
        root.mainloop()
    except KeyboardInterrupt:
        if app.is_running:
            app.hosts.restore()
            app.guard.stop()