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
from PIL import Image, ImageDraw
import pystray

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

    def get_stats(self):
        """Pobiera dane do panelu statystyk"""
        self.cursor.execute("SELECT SUM(duration_minutes) FROM sessions WHERE status='SUCCESS'")
        total_time = self.cursor.fetchone()[0]
        total_time = total_time if total_time is not None else 0

        self.cursor.execute("SELECT COUNT(*) FROM sessions WHERE status='SUCCESS'")
        success_count = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM sessions WHERE status='FAILED'")
        failed_count = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT task_name, duration_minutes, status, start_time FROM sessions ORDER BY start_time DESC LIMIT 10")
        recent = self.cursor.fetchall()

        return total_time, success_count, failed_count, recent

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
        self.kill_callback = kill_callback

    def _scan_and_kill(self):
        while self.running:
            for proc in psutil.process_iter(['name']):
                try:
                    proc_name = proc.info['name']
                    if proc_name and proc_name.lower() in self.blocked_processes:
                        print(f"[*] Strażnik ubił proces: {proc_name}")
                        proc.kill()
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
        self.root.geometry("450x580")
        self.root.resizable(False, False)

        self.db = DatabaseManager()
        self.settings = self.load_settings()

        self.time_left = 0
        self.total_session_time = 0
        self.is_running = False
        self.duration_minutes = 0
        self.task_name = ""
        self.notification_timer_id = None
        self.tray_icon = None

        # Tworzenie głównych widoków (Frames)
        self.setup_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.timer_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.settings_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.stats_frame = ctk.CTkFrame(self.root, fg_color="transparent")

        self.build_setup_ui()
        self.build_timer_ui()
        self.build_settings_ui()
        self.build_stats_ui()

        # Pokazanie widoku początkowego
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"Błąd odczytu pliku ustawień: {e}")
        
        return {
            "sites": ["facebook.com", "youtube.com", "instagram.com", "tiktok.com"],
            "processes": ["discord.exe", "steam.exe", "discord", "steam"]
        }

    def save_settings(self, new_settings):
        self.settings = new_settings
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(self.settings, f, indent=4)

    # ==========================
    # LOGIKA SYSTEM TRAY (Pasek Zadań)
    # ==========================
    def create_tray_image(self):
        """Generuje prostą ikonkę dla paska zadań (zielony kwadracik)"""
        image = Image.new('RGB', (64, 64), color=(44, 201, 133))
        dc = ImageDraw.Draw(image)
        dc.rectangle((16, 16, 48, 48), fill=(30, 30, 30))
        return image

    def hide_to_tray(self):
        """Chowa główne okno i uruchamia ikonę w Tray'u w osobnym wątku"""
        self.root.withdraw() # Ukrycie okna
        image = self.create_tray_image()
        
        # Menu pod prawym przyciskiem myszy na ikonce
        menu = pystray.Menu(pystray.MenuItem('Pokaż Focus Engine', self.show_from_tray))
        self.tray_icon = pystray.Icon("FocusEngine", image, "Focus Engine (Trwa sesja)", menu)
        
        # Uruchamiamy w tle, żeby nie zablokować pętli CustomTkinter
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_from_tray(self, icon, item):
        """Przywraca okno z Tray'a"""
        icon.stop()
        self.tray_icon = None
        self.root.after(0, self.root.deiconify) # Bezpieczne przywrócenie okna z wątku UI

    # ==========================
    # WIDOK GŁÓWNY (SETUP)
    # ==========================
    def build_setup_ui(self):
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

        bottom_btns_frame = ctk.CTkFrame(self.setup_frame, fg_color="transparent")
        bottom_btns_frame.pack(pady=(10, 0))

        settings_btn = ctk.CTkButton(bottom_btns_frame, text="⚙️ Ustawienia", width=140, fg_color="transparent", border_width=1, hover_color="#2c2c2c", text_color="gray", command=self.open_settings)
        settings_btn.pack(side="left", padx=5)

        stats_btn = ctk.CTkButton(bottom_btns_frame, text="📊 Statystyki", width=140, fg_color="transparent", border_width=1, hover_color="#2c2c2c", text_color="gray", command=self.open_stats)
        stats_btn.pack(side="right", padx=5)

    def update_time_label(self, value):
        self.time_label.configure(text=f"Czas trwania: {int(value)} min")

    # ==========================
    # WIDOK STATYSTYK
    # ==========================
    def build_stats_ui(self):
        title = ctk.CTkLabel(self.stats_frame, text="📊 Twoje Statystyki", font=("Helvetica", 22, "bold"))
        title.pack(pady=(10, 20))

        self.stats_total_label = ctk.CTkLabel(self.stats_frame, text="Łączny czas: 0 min", font=("Helvetica", 20, "bold"), text_color="#2CC985")
        self.stats_total_label.pack(pady=(5, 5))

        self.stats_success_label = ctk.CTkLabel(self.stats_frame, text="Ukończone sesje: 0 ✅", font=("Helvetica", 14))
        self.stats_success_label.pack(pady=(2, 2))

        self.stats_failed_label = ctk.CTkLabel(self.stats_frame, text="Przerwane sesje: 0 ❌ (Zwiędłe drzewa 🥀)", font=("Helvetica", 14), text_color="#E74C3C")
        self.stats_failed_label.pack(pady=(2, 20))

        ctk.CTkLabel(self.stats_frame, text="Ostatnie zadania:", font=("Helvetica", 12, "bold")).pack(anchor="w", padx=20)
        self.recent_sessions_textbox = ctk.CTkTextbox(self.stats_frame, width=410, height=180, state="disabled")
        self.recent_sessions_textbox.pack(pady=(5, 20), padx=20)

        back_btn = ctk.CTkButton(self.stats_frame, text="Wróć do Menu", width=200, font=("Helvetica", 12, "bold"), command=self.close_stats)
        back_btn.pack()

    def open_stats(self):
        total_time, success_count, failed_count, recent = self.db.get_stats()

        hours, mins = divmod(total_time, 60)
        time_str = f"{hours}h {mins}m" if hours > 0 else f"{mins} min"

        self.stats_total_label.configure(text=f"Łączny czas skupienia: {time_str}")
        self.stats_success_label.configure(text=f"Ukończone sesje: {success_count} ✅")
        self.stats_failed_label.configure(text=f"Przerwane sesje: {failed_count} ❌ (Zwiędłe drzewa 🥀)")

        self.recent_sessions_textbox.configure(state="normal")
        self.recent_sessions_textbox.delete("1.0", tk.END)

        if not recent:
            self.recent_sessions_textbox.insert("1.0", "Jeszcze brak sesji. Zasadź swoje pierwsze drzewko!\n")
        else:
            for task, duration, status, start_time in recent:
                try:
                    dt = datetime.strptime(start_time.split('.')[0], "%Y-%m-%d %H:%M:%S")
                    date_str = dt.strftime("%d.%m %H:%M")
                except:
                    date_str = start_time[:10]

                icon = "🌳" if status == "SUCCESS" else "🥀"
                self.recent_sessions_textbox.insert(tk.END, f"{date_str} | {duration} min | {task} {icon}\n")

        self.recent_sessions_textbox.configure(state="disabled")

        self.setup_frame.pack_forget()
        self.stats_frame.pack(fill="both", expand=True, padx=20, pady=20)

    def close_stats(self):
        self.stats_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)

    # ==========================
    # WIDOK USTAWIEŃ
    # ==========================
    def build_settings_ui(self):
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
        self.setup_frame.pack_forget()
        self.settings_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.sites_textbox.delete("1.0", tk.END)
        self.sites_textbox.insert("1.0", "\n".join(self.settings["sites"]))

        self.processes_textbox.delete("1.0", tk.END)
        self.processes_textbox.insert("1.0", "\n".join(self.settings["processes"]))

    def close_settings(self):
        self.settings_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)

    def save_and_close_settings(self):
        raw_sites = self.sites_textbox.get("1.0", tk.END).split("\n")
        sites = [s.strip() for s in raw_sites if s.strip()]

        raw_processes = self.processes_textbox.get("1.0", tk.END).split("\n")
        processes = [p.strip() for p in raw_processes if p.strip()]

        new_settings = {"sites": sites, "processes": processes}
        self.save_settings(new_settings)
        self.close_settings()

    # ==========================
    # WIDOK TIMERA (SESJA)
    # ==========================
    def build_timer_ui(self):
        self.current_task_label = ctk.CTkLabel(self.timer_frame, text="Zadanie...", font=("Helvetica", 16), text_color="gray")
        self.current_task_label.pack(pady=(20, 5))

        self.tree_label = ctk.CTkLabel(self.timer_frame, text="🌱", font=("Helvetica", 90))
        self.tree_label.pack(pady=(10, 10))

        self.timer_display = ctk.CTkLabel(self.timer_frame, text="00:00", font=("Helvetica", 70, "bold"), text_color="#2CC985")
        self.timer_display.pack(pady=(5, 30))

        stop_btn = ctk.CTkButton(self.timer_frame, text="PODDAJĘ SIĘ (ZABIJ DRZEWKO)", fg_color="#E74C3C", hover_color="#C0392B", height=40, width=250, font=("Helvetica", 14, "bold"), command=self.stop_session)
        stop_btn.pack()

        # Nowy przycisk minimalizacji do paska zadań (Tray)
        tray_btn = ctk.CTkButton(self.timer_frame, text="⬇ Zwiń do paska (Tray)", fg_color="transparent", border_width=1, text_color="gray", command=self.hide_to_tray)
        tray_btn.pack(pady=(15, 0))

        self.notification_label = ctk.CTkLabel(self.timer_frame, text="", font=("Helvetica", 13, "bold"), text_color="#E74C3C")
        self.notification_label.pack(pady=(10, 0))

    def notify_killed(self, proc_name):
        self.root.after(0, self.show_kill_notification, proc_name)

    def show_kill_notification(self, proc_name):
        self.notification_label.configure(text=f"🛑 Próba włączenia aplikacji '{proc_name}' zablokowana!")
        if self.notification_timer_id is not None:
            self.root.after_cancel(self.notification_timer_id)
        self.notification_timer_id = self.root.after(4000, self.clear_notification)

    def clear_notification(self):
        self.notification_label.configure(text="")
        self.notification_timer_id = None

    def start_session(self):
        task = self.task_entry.get().strip()
        mins = int(self.time_slider.get())

        if not task:
            messagebox.showwarning("Brak zadania", "Proszę wpisać nad czym będziesz pracować!")
            return

        self.task_name = task
        self.duration_minutes = mins
        self.total_session_time = mins * 60
        self.time_left = self.total_session_time
        self.is_running = True

        self.current_task_label.configure(text=f"Pracujesz nad:\n{self.task_name}")
        self.tree_label.configure(text="🌱")
        self.clear_notification()

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
            
            if self.total_session_time > 0:
                progress = (self.total_session_time - self.time_left) / self.total_session_time
                if progress < 0.25:
                    self.tree_label.configure(text="🌱")
                elif progress < 0.50:
                    self.tree_label.configure(text="🌿")
                elif progress < 0.75:
                    self.tree_label.configure(text="🪴")
                elif progress < 0.95:
                    self.tree_label.configure(text="🌳")
                else:
                    self.tree_label.configure(text="🍎")

            self.root.after(1000, self.update_timer)
        elif self.is_running and self.time_left <= 0:
            self.finish_session("SUCCESS")

    def finish_session(self, status):
        # Automatyczne przywracanie z paska (jeśli była schowana)
        if self.tray_icon is not None:
            try:
                self.tray_icon.stop()
            except:
                pass
            self.tray_icon = None
            self.root.deiconify()

        self.is_running = False
        self.guard.stop()
        self.hosts.restore()
        self.db.log_session(self.task_name, self.duration_minutes, status)
        
        if status == "SUCCESS":
            print('\a')
            messagebox.showinfo("Sukces!", "Świetna robota! Wyhodowałeś piękne drzewo 🌳\nInternet i aplikacje odblokowane.")
        
        self.reset_ui()

    def stop_session(self):
        if messagebox.askyesno("Ostrzeżenie", "Czy na pewno chcesz przerwać? Twoje drzewko uschnie (🥀), a statystyki zostaną zepsute!"):
            self.is_running = False
            self.guard.stop()
            self.hosts.restore()
            self.db.log_session(self.task_name, self.duration_minutes, "FAILED")
            
            messagebox.showinfo("Porażka", "Twoje drzewko uschło 🥀. Nie poddawaj się, spróbuj ponownie później!")
            self.reset_ui()

    def reset_ui(self):
        self.timer_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)
        self.task_entry.delete(0, tk.END)
        self.clear_notification()

    def on_closing(self):
        if self.is_running:
            # Pytanie, czy użytkownik woli schować aplikację, czy ją na twardo zamknąć (i zabić drzewko)
            if messagebox.askyesno("Minimalizacja", "Trwa sesja Focus Mode!\n\nCzy chcesz ukryć aplikację do paska zadań zamiast ją wyłączać?"):
                self.hide_to_tray()
            else:
                messagebox.showwarning("Ostrzeżenie", "Zablokowano zamknięcie. Użyj 'Przerwij', aby zabić drzewko i wyjść.")
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