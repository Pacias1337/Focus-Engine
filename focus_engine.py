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
from tkinter import messagebox
import customtkinter as ctk

# --- KONFIGURACJA (CROSS-PLATFORM) ---
if os.name == 'nt': # Windows
    HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
else: # macOS / Linux
    HOSTS_PATH = "/etc/hosts"

BACKUP_PATH = HOSTS_PATH + ".backup"
LOCK_FILE = "session.lock"
DB_FILE = "focus_stats.db"

# Ustawienia motywu CustomTkinter
ctk.set_appearance_mode("dark")  # Tryby: "System" (domyślny), "Dark", "Light"
ctk.set_default_color_theme("green")  # Motywy: "blue" (domyślny), "green", "dark-blue"

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
        if not os.path.exists(BACKUP_PATH):
            shutil.copy(HOSTS_PATH, BACKUP_PATH)
        
        with open(LOCK_FILE, 'w') as f:
            f.write("running")

        with open(HOSTS_PATH, 'a') as file:
            file.write("\n# --- FOCUS MODE START ---\n")
            for site in self.blocked_sites:
                file.write(f"127.0.0.1 {site}\n")
                file.write(f"127.0.0.1 www.{site}\n")
            file.write("# --- FOCUS MODE END ---\n")

    def restore(self):
        if os.path.exists(BACKUP_PATH):
            shutil.copy(BACKUP_PATH, HOSTS_PATH)
            os.remove(BACKUP_PATH)
        
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)

    @staticmethod
    def check_crash_recovery():
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
            time.sleep(3)

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._scan_and_kill, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

class FocusApp:
    """Nowoczesny Interfejs Graficzny za pomocą CustomTkinter"""
    def __init__(self, root):
        self.root = root
        self.root.title("Focus Engine")
        self.root.geometry("450x450")
        self.root.resizable(False, False)

        # Inicjalizacja modułów
        self.db = DatabaseManager()
        ZABLOKOWANE_STRONY = ["facebook.com", "youtube.com", "instagram.com"]
        ZABLOKOWANE_PROCESY = ["discord.exe", "steam.exe", "discord", "steam"]
        
        self.hosts = HostsBlocker(ZABLOKOWANE_STRONY)
        self.guard = ProcessGuard(ZABLOKOWANE_PROCESY)

        self.time_left = 0
        self.is_running = False
        self.duration_minutes = 0
        self.task_name = ""

        # Tworzenie głównych widoków
        self.setup_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.timer_frame = ctk.CTkFrame(self.root, fg_color="transparent")

        self.build_setup_ui()
        self.build_timer_ui()

        # Pokazanie widoku początkowego
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Zabezpieczenie przed zamknięciem okna "igreksem"
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def build_setup_ui(self):
        """Buduje widok konfiguracji (formularz)"""
        # Nagłówek
        title = ctk.CTkLabel(self.setup_frame, text="Zacznij Skupienie", font=("Helvetica", 28, "bold"))
        title.pack(pady=(20, 30))

        # Wejście tekstu
        self.task_entry = ctk.CTkEntry(self.setup_frame, placeholder_text="Nad czym będziesz pracować?", width=300, height=40, font=("Helvetica", 14))
        self.task_entry.pack(pady=(0, 20))

        # Dynamiczna etykieta czasu
        self.time_label = ctk.CTkLabel(self.setup_frame, text="Czas trwania: 25 min", font=("Helvetica", 14))
        self.time_label.pack(anchor="w", padx=55)

        # Suwak czasu (Slider) zamiast nudnego pola tekstowego
        self.time_slider = ctk.CTkSlider(self.setup_frame, from_=1, to=120, number_of_steps=119, width=300, command=self.update_time_label)
        self.time_slider.set(25) # Domyślnie 25 minut
        self.time_slider.pack(pady=(5, 30))

        # Duży przycisk START
        start_btn = ctk.CTkButton(self.setup_frame, text="ROZPOCZNIJ SESJĘ", height=50, width=300, font=("Helvetica", 16, "bold"), command=self.start_session)
        start_btn.pack()

    def update_time_label(self, value):
        """Aktualizuje tekst nad suwakiem podczas przeciągania"""
        self.time_label.configure(text=f"Czas trwania: {int(value)} min")

    def build_timer_ui(self):
        """Buduje widok odliczania (ukryty na start)"""
        # Etykieta obecnego zadania
        self.current_task_label = ctk.CTkLabel(self.timer_frame, text="Zadanie...", font=("Helvetica", 16), text_color="gray")
        self.current_task_label.pack(pady=(30, 10))

        # Wielki zegar
        self.timer_display = ctk.CTkLabel(self.timer_frame, text="00:00", font=("Helvetica", 80, "bold"), text_color="#2CC985")
        self.timer_display.pack(pady=(20, 40))

        # Przycisk przerwania
        stop_btn = ctk.CTkButton(self.timer_frame, text="PODDAJĘ SIĘ (PRZERWIJ)", fg_color="#E74C3C", hover_color="#C0392B", height=40, width=250, font=("Helvetica", 14, "bold"), command=self.stop_session)
        stop_btn.pack()

    def start_session(self):
        """Logika uruchamiająca sesję i zamieniająca widoki"""
        task = self.task_entry.get().strip()
        mins = int(self.time_slider.get())

        if not task:
            messagebox.showwarning("Brak zadania", "Proszę wpisać nad czym będziesz pracować!")
            return

        self.task_name = task
        self.duration_minutes = mins
        self.time_left = mins * 60
        self.is_running = True

        # Aktualizacja tekstów w widoku timera
        self.current_task_label.configure(text=f"Pracujesz nad:\n{self.task_name}")

        # Włączanie blokad w tle
        self.hosts.apply_block()
        self.guard.start()

        # Przełączenie widoków (Frames)
        self.setup_frame.pack_forget()
        self.timer_frame.pack(fill="both", expand=True, padx=20, pady=20)

        self.update_timer()

    def update_timer(self):
        """Asynchroniczne odświeżanie timera"""
        if self.is_running and self.time_left > 0:
            mins, secs = divmod(self.time_left, 60)
            self.timer_display.configure(text=f"{mins:02d}:{secs:02d}")
            self.time_left -= 1
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
            messagebox.showinfo("Sukces!", "Świetna robota! Sesja zakończona sukcesem.\nInternet i aplikacje odblokowane.")
        
        self.reset_ui()

    def stop_session(self):
        """Przerwanie przez użytkownika"""
        if messagebox.askyesno("Ostrzeżenie", "Czy na pewno chcesz przerwać? Zepsuje to Twoje statystyki w bazie danych!"):
            self.is_running = False
            self.guard.stop()
            self.hosts.restore()
            self.db.log_session(self.task_name, self.duration_minutes, "FAILED")
            
            self.reset_ui()

    def reset_ui(self):
        """Powrót do początkowego formularza"""
        self.timer_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)
        self.task_entry.delete(0, tk.END)

    def on_closing(self):
        if self.is_running:
            messagebox.showwarning("Blokada", "Trwa sesja Focus Mode! Użyj przycisku 'Przerwij', jeśli musisz wyjść.")
        else:
            self.root.destroy()

def is_admin():
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

    HostsBlocker.check_crash_recovery()

    # Inicjalizacja okna CustomTkinter
    root = ctk.CTk()
    app = FocusApp(root)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        if app.is_running:
            app.hosts.restore()
            app.guard.stop()