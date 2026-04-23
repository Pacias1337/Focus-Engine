# 🌳 Focus Engine

**Focus Engine** is a modern Productivity & Focus application designed to eliminate distractions and foster healthy work habits. The project merges gamification techniques—such as growing virtual trees—with advanced system-level blocking of processes and websites.

## 🚀 Key Features

* 🛡️ **Multi-Level Blocking:** Restricts access to distracting websites by editing the system `hosts` file and actively terminating specified processes (e.g., Steam, Discord).
* 🌳 **Gamification:** Your deep work sessions provide life to a virtual tree. If you break your focus session prematurely, the tree withers.
* ⚙️ **App Scanner:** An intelligent scanner that automatically detects installed applications, allowing you to add them to your blocklist with a single click.
* 📊 **Advanced Statistics:** Track your daily focus time and task history. Includes a "streaks" system to keep you motivated and consistent.
* 🌑 **Modern UI:** A sleek, dark-themed interface built with **CustomTkinter**, featuring System Tray support for seamless background operation.
* 🛠️ **Crash Recovery:** Built-in safety mechanisms that automatically restore original system settings if the application closes unexpectedly.

## 🛠️ Technology Stack

* **Language:** Python 3.13+
* **GUI:** CustomTkinter (Modern Desktop UI)
* **Database:** SQLite3
* **System Libraries:** * `psutil` (Process management)
    * `pystray` & `Pillow` (System Tray integration)

## 📦 Installation & Setup

### For Users (Windows .exe)
1. Download the `FocusEngine.exe` from the **Releases** section.
2. Run the application and start focusing!
*Note: Administrator privileges are required for system-level blocking.*

### For Developers
1. **Clone the repository:**
   ```bash
   git clone [https://github.com/Pacias1337/Focus-Engine](https://github.com/Pacias1337/Focus-Engine)
