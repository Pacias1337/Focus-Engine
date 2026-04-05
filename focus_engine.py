import os
import sys
import time
import shutil
import ctypes
import threading
import sqlite3
import psutil
import json
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
SETTINGS_FILE = "settings.json"

# Ustawienia motywu CustomTkinter
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

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
    def __init__(self, blocked_processes, kill_callback=None):
        self.blocked_processes = [p.lower() for p in blocked_processes]
        self.running = False
        self.thread = None
        self.kill_callback = kill_callback # Funkcja wywoływana przy ubiciu procesu

    def _scan_and_kill(self):
        while self.running:
            for proc in psutil.process_iter(['name']):
                try:
                    proc_name = proc.info['name']
                    if proc_name and proc_name.lower() in self.blocked_processes:
                        print(f"[*] Strażnik ubił proces: {proc_name}")
                        proc.kill()
                        # Jeśli mamy podpięty interfejs, wyślij do niego sygnał
                        if self.kill_callback:
                            self.kill_callback(proc_name)
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
        self.root.geometry("450x550")
        self.root.resizable(False, False)

        # Inicjalizacja bazy
        self.db = DatabaseManager()
        
        # Wczytywanie ustawień z pliku (lub domyślnych, jeśli plik nie istnieje)
        self.settings = self.load_settings()

        self.time_left = 0
        self.is_running = False
        self.duration_minutes = 0
        self.task_name = ""
        self.notification_timer_id = None # ID dla timera czyszczącego komunikaty

        # Tworzenie głównych widoków (Frames)
        self.setup_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.timer_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.settings_frame = ctk.CTkFrame(self.root, fg_color="transparent")

        self.build_setup_ui()
        self.build_timer_ui()
        self.build_settings_ui()

        # Pokazanie widoku początkowego
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def load_settings(self):
        """Wczytuje zablokowane strony i procesy z pliku JSON"""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Błąd odczytu pliku ustawień: {e}")
        
        # Domyślne wartości przy pierwszym uruchomieniu
        return {
            "sites": ["facebook.com", "youtube.com", "instagram.com", "tiktok.com"],
            "processes": ["discord.exe", "steam.exe", "discord", "steam"]
        }

    def save_settings(self, new_settings):
        """Zapisuje ustawienia do pliku JSON"""
        self.settings = new_settings
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(self.settings, f, indent=4)

    def build_setup_ui(self):
        """Buduje główny widok konfiguracji (formularz)"""
        title = ctk.CTkLabel(self.setup_frame, text="Zacznij Skupienie", font=("Helvetica", 28, "bold"))
        title.pack(pady=(20, 30))

        self.task_entry = ctk.CTkEntry(self.setup_frame, placeholder_text="Nad czym będziesz pracować?", width=300, height=40, font=("Helvetica", 14))
        self.task_entry.pack(pady=(0, 20))

        self.time_label = ctk.CTkLabel(self.setup_frame, text="Czas trwania: 25 min", font=("Helvetica", 14))
        self.time_label.pack(anchor="w", padx=55)

        self.time_slider = ctk.CTkSlider(self.setup_frame, from_=1, to=120, number_of_steps=119, width=300, command=self.update_time_label)
        self.time_slider.set(25)
        self.time_slider.pack(pady=(5, 30))

        start_btn = ctk.CTkButton(self.setup_frame, text="ROZPOCZNIJ SESJĘ", height=50, width=300, font=("Helvetica", 16, "bold"), command=self.start_session)
        start_btn.pack(pady=(0, 20))

        settings_btn = ctk.CTkButton(self.setup_frame, text="⚙️ Ustawienia blokad", fg_color="transparent", border_width=1, hover_color="#2c2c2c", text_color="gray", command=self.open_settings)
        settings_btn.pack(pady=(10, 0))

    def update_time_label(self, value):
        self.time_label.configure(text=f"Czas trwania: {int(value)} min")

    def build_settings_ui(self):
        """Buduje widok panelu ustawień"""
        title = ctk.CTkLabel(self.settings_frame, text="⚙️ Ustawienia Blokad", font=("Helvetica", 22, "bold"))
        title.pack(pady=(10, 20))

        ctk.CTkLabel(self.settings_frame, text="Zablokowane strony (jedna w linijce):", font=("Helvetica", 12)).pack(anchor="w", padx=20)
        self.sites_textbox = ctk.CTkTextbox(self.settings_frame, width=410, height=120)
        self.sites_textbox.pack(pady=(5, 15), padx=20)

        ctk.CTkLabel(self.settings_frame, text="Zablokowane procesy (jeden w linijce):", font=("Helvetica", 12)).pack(anchor="w", padx=20)
        self.processes_textbox = ctk.CTkTextbox(self.settings_frame, width=410, height=120)
        self.processes_textbox.pack(pady=(5, 20), padx=20)

        btn_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20)

        cancel_btn = ctk.CTkButton(btn_frame, text="Anuluj", width=120, fg_color="transparent", border_width=1, command=self.close_settings)
        cancel_btn.pack(side="left")

        save_btn = ctk.CTkButton(btn_frame, text="Zapisz i Wróć", width=200, font=("Helvetica", 12, "bold"), command=self.save_and_close_settings)
        save_btn.pack(side="right")

    def open_settings(self):
        """Otwiera panel ustawień i ładuje obecne dane"""
        self.setup_frame.pack_forget()
        self.settings_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.sites_textbox.delete("1.0", tk.END)
        self.sites_textbox.insert("1.0", "\n".join(self.settings["sites"]))

        self.processes_textbox.delete("1.0", tk.END)
        self.processes_textbox.insert("1.0", "\n".join(self.settings["processes"]))

    def close_settings(self):
        """Wraca do menu bez zapisywania"""
        self.settings_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)

    def save_and_close_settings(self):
        """Zapisuje zmiany z okienek do JSON i wraca do menu"""
        raw_sites = self.sites_textbox.get("1.0", tk.END).split("\n")
        sites = [s.strip() for s in raw_sites if s.strip()]

        raw_processes = self.processes_textbox.get("1.0", tk.END).split("\n")
        processes = [p.strip() for p in raw_processes if p.strip()]

        new_settings = {"sites": sites, "processes": processes}
        self.save_settings(new_settings)
        self.close_settings()

    def build_timer_ui(self):
        """Buduje widok odliczania"""
        self.current_task_label = ctk.CTkLabel(self.timer_frame, text="Zadanie...", font=("Helvetica", 16), text_color="gray")
        self.current_task_label.pack(pady=(40, 10))

        self.timer_display = ctk.CTkLabel(self.timer_frame, text="00:00", font=("Helvetica", 80, "bold"), text_color="#2CC985")
        self.timer_display.pack(pady=(20, 30))

        stop_btn = ctk.CTkButton(self.timer_frame, text="PODDAJĘ SIĘ (PRZERWIJ)", fg_color="#E74C3C", hover_color="#C0392B", height=40, width=250, font=("Helvetica", 14, "bold"), command=self.stop_session)
        stop_btn.pack()

        # Miejsce na komunikaty o zablokowanych aplikacjach
        self.notification_label = ctk.CTkLabel(self.timer_frame, text="", font=("Helvetica", 13, "bold"), text_color="#E74C3C")
        self.notification_label.pack(pady=(30, 0))

    def notify_killed(self, proc_name):
        """Odbiera sygnał z wątku w tle i przekazuje do głównego wątku UI"""
        # Używamy root.after, aby bezpiecznie zmodyfikować UI z innego wątku
        self.root.after(0, self.show_kill_notification, proc_name)

    def show_kill_notification(self, proc_name):
        """Pokazuje czerwony komunikat pod timerem"""
        self.notification_label.configure(text=f"🛑 Próba włączenia aplikacji '{proc_name}' zablokowana!")
        
        # Jeśli był już włączony timer kasujący komunikat, anuluj go
        if self.notification_timer_id is not None:
            self.root.after_cancel(self.notification_timer_id)
            
        # Zleć usunięcie komunikatu za 4 sekundy
        self.notification_timer_id = self.root.after(4000, self.clear_notification)

    def clear_notification(self):
        """Czyści komunikat"""
        self.notification_label.configure(text="")
        self.notification_timer_id = None

    def start_session(self):
        """Logika uruchamiająca sesję z wczytanymi ustawieniami"""
        task = self.task_entry.get().strip()
        mins = int(self.time_slider.get())

        if not task:
            messagebox.showwarning("Brak zadania", "Proszę wpisać nad czym będziesz pracować!")
            return

        self.task_name = task
        self.duration_minutes = mins
        self.time_left = mins * 60
        self.is_running = True

        self.current_task_label.configure(text=f"Pracujesz nad:\n{self.task_name}")
        self.clear_notification() # Upewnij się, że nie ma starych powiadomień

        # Inicjalizacja strażników (przekazujemy funkcję callback do powiadomień UI)
        self.hosts = HostsBlocker(self.settings["sites"])
        self.guard = ProcessGuard(self.settings["processes"], kill_callback=self.notify_killed)

        self.hosts.apply_block()
        self.guard.start()

        self.setup_frame.pack_forget()
        self.timer_frame.pack(fill="both", expand=True, padx=20, pady=20)

        self.update_timer()

    def update_timer(self):
        if self.is_running and self.time_left > 0:
            mins, secs = divmod(self.time_left, 60)
            self.timer_display.configure(text=f"{mins:02d}:{secs:02d}")
            self.time_left -= 1
            self.root.after(1000, self.update_timer)
        elif self.is_running and self.time_left <= 0:
            self.finish_session("SUCCESS")

    def finish_session(self, status):
        self.is_running = False
        self.guard.stop()
        self.hosts.restore()
        self.db.log_session(self.task_name, self.duration_minutes, status)
        
        if status == "SUCCESS":
            print('\a')
            messagebox.showinfo("Sukces!", "Świetna robota! Sesja zakończona sukcesem.\nInternet i aplikacje odblokowane.")
        
        self.reset_ui()

    def stop_session(self):
        if messagebox.askyesno("Ostrzeżenie", "Czy na pewno chcesz przerwać? Zepsuje to Twoje statystyki w bazie danych!"):
            self.is_running = False
            self.guard.stop()
            self.hosts.restore()
            self.db.log_session(self.task_name, self.duration_minutes, "FAILED")
            
            self.reset_ui()

    def reset_ui(self):
        self.timer_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)
        self.task_entry.delete(0, tk.END)
        self.clear_notification()

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

    root = ctk.CTk()
    app = FocusApp(root)
    
    try:
        root.mainloop()
    except KeyboardInterrupt:
        if app.is_running:
            app.hosts.restore()
            app.guard.stop()