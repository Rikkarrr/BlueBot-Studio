# 🌀 BlueBot Studio

**BlueBot Studio** is a free-to-use and open-source collection of fully automated dungeon bots for **Blue Protocol: Star Resonance**  
(Kanamia, Tina, Towering) featuring a modern graphical launcher built with Python.  
It’s designed for **Windows**, optimized for fullscreen gameplay, and meant for hobby/AFK dungeon farming — free and simple to use.

> ⚠️ This bot is purely experimental and made for educational purposes only.  
> Use at your own discretion.

---

## 💻 Requirements

- **Windows 10/11 (64-bit)**
- **Visual Studio Code** (for running and editing the scripts)
- **Python 3.14** (latest version from [python.org](https://www.python.org/ftp/python/3.14.0/python-3.14.0-amd64.exe))
  - During setup, check **“Add Python to PATH”**
  - Install for **all users**

---

## 📦 Installation

1. **Download the Repository**
   - Click **Code → Download ZIP**
   - Unzip it to a new folder named `BlueBot`
   - You should now have this structure:
     ```
     BlueBot/
     ├─ bot_gui.py
     ├─ towering_bot.py
     ├─ tina_bot.py
     ├─ kanamia_bot.py
     ├─ assets/
     └─ requirements.txt
     ```

2. **Open in Visual Studio Code**
   - Open the `BlueBot` folder via **File → Open Folder…**
   - VS Code should detect Python automatically
   - Install the **Python Extensions** from Microsoft in Visual Studio Code

3. **Select the Python 3.14 Interpreter**
   - Press `Ctrl + Shift + P` → “Python: Select Interpreter”
   - Choose the one that says **Python 3.14** (or any newer interpreter)
   - Sometimes you have to switch interpreters to see which one resolves dependency issues  
     → Press `Ctrl + Shift + P` and click through available interpreters

4. **Note:**  
   PyWinAuto may occasionally appear as a “problem” in VS Code — you can **ignore** this.  
   If needed, run the commands via **CMD** instead of VS Code’s terminal:
   ```bash
   cd \your\path\
   # Replace \your\path\ with the path to your BlueBot folder
   ```

---

## ⚙️ Dependency Installation

Make sure pip is up to date first:

```bash
py -3.14 -m pip install -U pip setuptools wheel
```

Then install dependencies (in order):

```bash
# Upgrade pip again just in case
py -3.14 -m pip install --upgrade pip setuptools wheel

# Install required packages
py -3.14 -m pip install --prefer-binary numpy==2.3.4 opencv-python mss PyAutoGUI pynput pywinauto pywin32 Pillow
```

Or simply:

```bash
py -3.14 -m pip install -r requirements.txt
```

If you encounter issues with `numpy` or `opencv-python`, try forcing binary builds:

```bash
py -3.14 -m pip install --only-binary=:all: numpy==2.3.4
```

Finally, to make sure everything is working, run:

```bash
py -u bot_gui.py
```

---

## 🧠 How It Works (Quick Abstract)

### 1. Start BlueBot Studio
```bash
py -u bot_gui.py
```

### 2. Pick the Correct Monitor
- The bot uses monitor indexing (`1` = primary, `2` = secondary, etc.)
- Check your monitor number in **Windows Display Settings → Identify**
- Set that number in the GUI under **Monitor Index**

### 3. Choose Your Bot
- `Kanamia`, `Tina`, or `Towering`
- Press **▶ Start** in the GUI
- Use **F8 / F9 / F10** for **Start / Pause / Exit**

### 4. Sit Back
- The bot detects UI elements via OpenCV and automates dungeon runs.
- One good night of AFK farming can yield a lot.

---

## 🧰 Optional — Create an Executable (.exe)

If you want to bundle everything into a standalone `.exe`:

1. Install **PyInstaller**:
   ```bash
   py -3.14 -m pip install pyinstaller
   ```

2. Run the build command:
   ```bash
   py -3.14 -m PyInstaller --noconsole --onefile bot_gui.py
   ```

3. After completion, your `.exe` will be in the `dist/` folder.  
   Double-click it to launch **BlueBot Studio** without opening VS Code.

> Keep in mind that the `.exe` will be larger and might trigger antivirus false positives — normal for Python packagers.

---

## 🧩 Troubleshooting

### Bot not clicking anything?
- Ensure your game is running **fullscreen** on the monitor you selected.
- Check that the in-game language and UI resolution match the template screenshots in `assets/`.
- Run VS Code as **Administrator** if necessary.

### Import or DLL errors?
Re-run:
```bash
py -3.14 -m pip install --upgrade pip setuptools wheel
py -3.14 -m pip install --prefer-binary numpy==2.3.4 opencv-python mss PyAutoGUI pynput pywinauto pywin32 Pillow
```

---

## 🧑‍💻 Contact & Notes

- Discord: **zzrikka**
- I don’t have a Discord server yet — maybe in the future.
- Feel free to message me if you find bugs or have questions.

> I’m just a hobby programmer — this bot could definitely be improved,  
> but for a free project, it works quite well!  
> One night of AFK dungeon farming can already give you plenty.

---

## 🪙 License

This project is released for **personal use only** —  
no resale, redistribution, or public release under your name without credit.

---

**Enjoy BlueBot Studio.**  
Stay safe, have fun, and happy farming! 🌙
