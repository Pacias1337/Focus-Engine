import os
import sys
import time
import shutil
import ctypes
import threading
import sqlite3
import psutil
import json
import random
from datetime import datetime, timedelta
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

# Memiczne/Gen Z Cytaty Motywacyjne
GEN_Z_QUOTES = [
    "Mniej TikToka, więcej kodu. 💻",
    "Touch grass... ale dopiero po sesji. 🌿",
    "Zrób to dla przyszłego siebie (i dla portfolio). 🚀",
    "Bądź delulu, dopóki to nie stanie się trululu. Do roboty! ✨",
    "Skup się. Zaraz będziesz mógł scrollować. 📱",
    "GigaChad skupienia. Nie poddawaj się. 🗿",
    "Slay the day! ✨💅",
    "POV: jesteś programistą i właśnie fixujesz bugi. 🧑‍💻",
    "NPC się poddają. Główny bohater pracuje dalej. 🎮",
    "Zostaw tego Discorda w spokoju. 🤫"
]

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

        today_str = datetime.now().strftime("%Y-%m-%d")
        self.cursor.execute("SELECT SUM(duration_minutes) FROM sessions WHERE status='SUCCESS' AND substr(start_time, 1, 10) = ?", (today_str,))
        today_time = self.cursor.fetchone()[0]
        today_time = today_time if today_time is not None else 0

        self.cursor.execute("SELECT COUNT(*) FROM sessions WHERE status='SUCCESS'")
        success_count = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT COUNT(*) FROM sessions WHERE status='FAILED'")
        failed_count = self.cursor.fetchone()[0]

        self.cursor.execute("SELECT task_name, duration_minutes, status, start_time FROM sessions ORDER BY start_time DESC LIMIT 10")
        recent = self.cursor.fetchall()

        return total_time, today_time, success_count, failed_count, recent

    def get_streak(self):
        """Oblicza liczbę dni z rzędu (Streak / Płomienie 🔥)"""
        self.cursor.execute("SELECT DISTINCT substr(start_time, 1, 10) FROM sessions WHERE status='SUCCESS' ORDER BY start_time DESC")
        rows = self.cursor.fetchall()
        
        if not rows:
            return 0
            
        streak = 0
        today = datetime.now().date()
        try:
            last_date = datetime.strptime(rows[0][0], "%Y-%m-%d").date()
        except:
            return 0

        if (today - last_date).days > 1:
            return 0
            
        current_expected = last_date
        for row in rows:
            row_date = datetime.strptime(row[0], "%Y-%m-%d").date()
            if row_date == current_expected:
                streak += 1
                current_expected -= timedelta(days=1)
            else:
                break
        return streak

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

        self.setup_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.timer_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.settings_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.stats_frame = ctk.CTkFrame(self.root, fg_color="transparent")

        self.build_setup_ui()
        self.build_timer_ui()
        self.build_settings_ui()
        self.build_stats_ui()

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
        image = Image.new('RGB', (64, 64), color=(44, 201, 133))
        dc = ImageDraw.Draw(image)
        dc.rectangle((16, 16, 48, 48), fill=(30, 30, 30))
        return image

    def hide_to_tray(self):
        self.root.withdraw()
        image = self.create_tray_image()
        
        menu = pystray.Menu(pystray.MenuItem('Pokaż Focus Engine', self.show_from_tray))
        self.tray_icon = pystray.Icon("FocusEngine", image, "Focus Engine (Trwa sesja)", menu)
        
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def show_from_tray(self, icon, item):
        icon.stop()
        self.tray_icon = None
        self.root.after(0, self.root.deiconify)

    # ==========================
    # WIDOK GŁÓWNY (SETUP)
    # ==========================
    def build_setup_ui(self):
        header_frame = ctk.CTkFrame(self.setup_frame, fg_color="transparent")
        header_frame.pack(fill="x", pady=(10, 20))

        title = ctk.CTkLabel(header_frame, text="Zacznij Skupienie", font=("Helvetica", 28, "bold"))
        title.pack(side="left", padx=10)

        streak = self.db.get_streak()
        self.main_streak_label = ctk.CTkLabel(header_frame, text=f"{streak} 🔥", font=("Helvetica", 26, "bold"), text_color="#FFA500")
        self.main_streak_label.pack(side="right", padx=10)

        self.category_var = ctk.StringVar(value="💻 Kodowanie")
        categories = ["💻 Kodowanie", "📚 Nauka", "🧘‍♂️ Relaks", "🧹 Obowiązki", "🚀 Inne"]
        self.category_menu = ctk.CTkOptionMenu(self.setup_frame, values=categories, variable=self.category_var, width=300, height=35, font=("Helvetica", 13))
        self.category_menu.pack(pady=(0, 10))

        self.task_entry = ctk.CTkEntry(self.setup_frame, placeholder_text="Szczegóły (np. projekt zaliczeniowy)", width=300, height=40, font=("Helvetica", 14))
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
        title.pack(pady=(10, 15))

        metrics_frame = ctk.CTkFrame(self.stats_frame, fg_color="#2b2b2b", corner_radius=10)
        metrics_frame.pack(fill="x", padx=20, pady=(0, 15), ipady=10)

        self.stats_today_label = ctk.CTkLabel(metrics_frame, text="Dzisiaj: 0 min", font=("Helvetica", 18, "bold"), text_color="#2CC985")
        self.stats_today_label.pack(pady=(5, 5))

        self.stats_total_label = ctk.CTkLabel(metrics_frame, text="Łącznie: 0 min", font=("Helvetica", 13), text_color="#AAAAAA")
        self.stats_total_label.pack(pady=(0, 10))

        self.stats_success_label = ctk.CTkLabel(metrics_frame, text="Ukończone sesje: 0 ✅", font=("Helvetica", 13))
        self.stats_success_label.pack()

        self.stats_failed_label = ctk.CTkLabel(metrics_frame, text="Przerwane sesje: 0 ❌", font=("Helvetica", 13), text_color="#E74C3C")
        self.stats_failed_label.pack()

        ctk.CTkLabel(self.stats_frame, text="Ostatnie zadania:", font=("Helvetica", 12, "bold")).pack(anchor="w", padx=20)
        self.recent_sessions_textbox = ctk.CTkTextbox(self.stats_frame, width=410, height=160, state="disabled")
        self.recent_sessions_textbox.pack(pady=(5, 15), padx=20)

        back_btn = ctk.CTkButton(self.stats_frame, text="Wróć do Menu", width=200, font=("Helvetica", 12, "bold"), command=self.close_stats)
        back_btn.pack()

    def open_stats(self):
        total_time, today_time, success_count, failed_count, recent = self.db.get_stats()

        h_total, m_total = divmod(total_time, 60)
        total_str = f"{h_total}h {m_total}m" if h_total > 0 else f"{m_total} min"

        h_today, m_today = divmod(today_time, 60)
        today_str = f"{h_today}h {m_today}m" if h_today > 0 else f"{m_today} min"

        self.stats_today_label.configure(text=f"Dzisiejsze skupienie: {today_str}")
        self.stats_total_label.configure(text=f"Łączny czas historii: {total_str}")
        self.stats_success_label.configure(text=f"Ukończone sesje: {success_count} ✅")
        self.stats_failed_label.configure(text=f"Przerwane sesje: {failed_count} ❌")

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
    # WIDOK USTAWIEŃ I SKANER APLIKACJI
    # ==========================
    def build_settings_ui(self):
        title = ctk.CTkLabel(self.settings_frame, text="⚙️ Ustawienia Blokad", font=("Helvetica", 22, "bold"))
        title.pack(pady=(10, 20))

        ctk.CTkLabel(self.settings_frame, text="Zablokowane strony (jedna w linijce):", font=("Helvetica", 12)).pack(anchor="w", padx=20)
        self.sites_textbox = ctk.CTkTextbox(self.settings_frame, width=410, height=90)
        self.sites_textbox.pack(pady=(5, 10), padx=20)

        # Nagłówek dla procesów z przyciskiem skanowania obok
        proc_header_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        proc_header_frame.pack(fill="x", padx=20)
        
        ctk.CTkLabel(proc_header_frame, text="Zablokowane procesy:", font=("Helvetica", 12)).pack(side="left")
        
        scan_btn = ctk.CTkButton(proc_header_frame, text="🔍 Skanuj komputer", width=120, height=24, font=("Helvetica", 11), fg_color="#2C82C9", hover_color="#1F5D90", command=self.open_app_scanner)
        scan_btn.pack(side="right")

        self.processes_textbox = ctk.CTkTextbox(self.settings_frame, width=410, height=90)
        self.processes_textbox.pack(pady=(5, 15), padx=20)

        btn_frame = ctk.CTkFrame(self.settings_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20)

        cancel_btn = ctk.CTkButton(btn_frame, text="Anuluj", width=120, fg_color="transparent", border_width=1, command=self.close_settings)
        cancel_btn.pack(side="left")

        save_btn = ctk.CTkButton(btn_frame, text="Zapisz i Wróć", width=200, font=("Helvetica", 12, "bold"), command=self.save_and_close_settings)
        save_btn.pack(side="right")

    def scan_apps(self):
        """Skanuje pliki systemowe i aktualnie uruchomione procesy by wyciągnąć nazwy aplikacji"""
        detected_apps = set()
        
        # 1. macOS: Skanowanie folderu /Applications (Najbardziej niezawodne dla Mac)
        if sys.platform == 'darwin':
            try:
                for app_dir in ['/Applications', os.path.expanduser('~/Applications')]:
                    if os.path.exists(app_dir):
                        for item in os.listdir(app_dir):
                            if item.endswith('.app'):
                                detected_apps.add(item.replace('.app', ''))
            except Exception as e:
                print(f"Błąd skanowania /Applications: {e}")

        # 2. Wszystkie platformy: Skanowanie aktualnie uruchomionych procesów użytkownika
        try:
            for proc in psutil.process_iter(['name']):
                name = proc.info.get('name')
                if name:
                    name_lower = name.lower()
                    # Ignorowanie ukrytych procesów systemowych by nie robić śmietnika
                    system_procs = ['svchost.exe', 'explorer.exe', 'system', 'kernel_task', 'launchd', 'windowserver', 'sysmond']
                    if name_lower not in system_procs and not name_lower.startswith(('com.apple', 'microsoft.')):
                        detected_apps.add(name)
        except Exception as e:
             print(f"Błąd skanowania procesów: {e}")

        # Sortowanie alfabetyczne
        return sorted([app for app in detected_apps if app], key=lambda x: x.lower())

    def open_app_scanner(self):
        """Otwiera nowe okienko (popup) z listą aplikacji i checkboxami"""
        popup = ctk.CTkToplevel(self.root)
        popup.title("Skaner Aplikacji")
        popup.geometry("380x450")
        popup.attributes('-topmost', True) # Trzyma na wierzchu
        popup.grab_set() # Blokuje klikanie w inne okienka w tle

        ctk.CTkLabel(popup, text="Wybierz programy do blokowania", font=("Helvetica", 16, "bold")).pack(pady=(15, 5))
        ctk.CTkLabel(popup, text="Znaleziono zainstalowane oraz uruchomione aplikacje", font=("Helvetica", 11), text_color="gray").pack(pady=(0, 10))
        
        scroll_frame = ctk.CTkScrollableFrame(popup, width=320, height=280)
        scroll_frame.pack(pady=5, padx=10, fill="both", expand=True)

        apps = self.scan_apps()
        checkbox_vars = {}

        # Sprawdzamy co już jest wpisane w Textboxie, by od razu to zaznaczyć
        current_manual_apps = [a.strip() for a in self.processes_textbox.get("1.0", tk.END).split('\n') if a.strip()]
        current_manual_apps_lower = [a.lower() for a in current_manual_apps]
        
        for app in apps:
            var = tk.BooleanVar(value=(app.lower() in current_manual_apps_lower))
            chk = ctk.CTkCheckBox(scroll_frame, text=app, variable=var)
            chk.pack(anchor="w", pady=4, padx=5)
            checkbox_vars[app] = var

        def save_selection():
            final_list = []
            
            # Dodajemy zachowane aplikacje z textboxa (nawet te wpisane ręcznie, których nie wykrył skaner)
            for m_app in current_manual_apps:
                matched_in_scanner = next((a for a in apps if a.lower() == m_app.lower()), None)
                if matched_in_scanner:
                    if checkbox_vars[matched_in_scanner].get():
                        final_list.append(m_app)
                else:
                    final_list.append(m_app)
                    
            # Dodajemy nowe zaznaczone aplikacje ze skanera
            for app, var in checkbox_vars.items():
                if var.get() and not any(a.lower() == app.lower() for a in final_list):
                    final_list.append(app)
                    
            self.processes_textbox.delete("1.0", tk.END)
            self.processes_textbox.insert("1.0", "\n".join(final_list))
            popup.destroy()

        ctk.CTkButton(popup, text="Dodaj zaznaczone", font=("Helvetica", 14, "bold"), command=save_selection).pack(pady=15)

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
        self.current_task_label.pack(pady=(15, 5))

        self.tree_label = ctk.CTkLabel(self.timer_frame, text="🌱", font=("Helvetica", 80))
        self.tree_label.pack(pady=(5, 5))

        self.timer_display = ctk.CTkLabel(self.timer_frame, text="00:00", font=("Helvetica", 70, "bold"), text_color="#2CC985")
        self.timer_display.pack(pady=(5, 10))

        self.quote_label = ctk.CTkLabel(self.timer_frame, text="...", font=("Helvetica", 12, "italic"), text_color="#888888", wraplength=350)
        self.quote_label.pack(pady=(0, 25))

        stop_btn = ctk.CTkButton(self.timer_frame, text="PODDAJĘ SIĘ (ZABIJ DRZEWKO)", fg_color="#E74C3C", hover_color="#C0392B", height=40, width=250, font=("Helvetica", 14, "bold"), command=self.stop_session)
        stop_btn.pack()

        tray_btn = ctk.CTkButton(self.timer_frame, text="⬇ Zwiń do paska (Tray)", fg_color="transparent", border_width=1, text_color="gray", command=self.hide_to_tray)
        tray_btn.pack(pady=(15, 0))

        self.notification_label = ctk.CTkLabel(self.timer_frame, text="", font=("Helvetica", 13, "bold"), text_color="#E74C3C")
        self.notification_label.pack(pady=(5, 0))

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
        category = self.category_var.get()
        task_details = self.task_entry.get().strip()
        mins = int(self.time_slider.get())

        if not task_details:
            task_details = "Praca domyślna"

        self.task_name = f"{category} - {task_details}"
        self.duration_minutes = mins
        self.total_session_time = mins * 60
        self.time_left = self.total_session_time
        self.is_running = True

        self.current_task_label.configure(text=f"Pracujesz nad:\n{self.task_name}")
        self.tree_label.configure(text="🌱")
        self.quote_label.configure(text=random.choice(GEN_Z_QUOTES))
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
        dialog = ctk.CTkInputDialog(
            text="Impulsywna decyzja? 🛑\nAby zabić drzewko i wyłączyć blokady, przepisz dokładnie:\n\npoddaję się", 
            title="Ostrzeżenie przed przerwaniem"
        )
        user_input = dialog.get_input()

        if user_input is None:
            return

        user_input = user_input.lower().strip()
        if user_input in ["poddaję się", "poddaje sie", "poddaję sie"]:
            self.is_running = False
            self.guard.stop()
            self.hosts.restore()
            self.db.log_session(self.task_name, self.duration_minutes, "FAILED")
            
            messagebox.showinfo("Porażka", "Twoje drzewko uschło 🥀. Nie poddawaj się, spróbuj ponownie później!")
            self.reset_ui()
        else:
            messagebox.showinfo("Ocalono!", "Literówka (albo podświadomie wcale nie chciałeś tego psuć).\nWracaj do pracy, GigaChadzie! 🗿")

    def reset_ui(self):
        self.main_streak_label.configure(text=f"{self.db.get_streak()} 🔥")
        
        self.timer_frame.pack_forget()
        self.setup_frame.pack(fill="both", expand=True, padx=20, pady=20)
        self.task_entry.delete(0, tk.END)
        self.clear_notification()

    def on_closing(self):
        if self.is_running:
            if messagebox.askyesno("Minimalizacja", "Trwa sesja Focus Mode!\n\nCzy chcesz ukryć aplikację do paska zadań zamiast ją wyłączać?"):
                self.hide_to_tray()
            else:
                messagebox.showwarning("Ostrzeżenie", "Zablokowano zamknięcie. Użyj przycisku 'Poddaję się' wewnątrz aplikacji, jeśli naprawdę musisz wyjść.")
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