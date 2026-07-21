import os
import sys
import subprocess
import time
import webbrowser

TARGET_DIR = r"C:\Projects\AI_Agent_Test"
os.chdir(TARGET_DIR)

print("🔄 Updating Local Agent Arena port to 7878...")

# 1. Kill any existing server process
try:
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "taskkill /F /IM python.exe /T"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
except Exception:
    pass

# 2. Update main.py port to 7878
with open("main.py", "r", encoding="utf-8") as f:
    main_code = f.read()

main_code_updated = main_code.replace("port=8000", "port=7878").replace("port= 8000", "port= 7878")

with open("main.py", "w", encoding="utf-8") as f:
    f.write(main_code_updated)

print("✅ main.py updated (Uvicorn running on port 7878).")

# 3. Update index.html endpoint to port 7878
with open("index.html", "r", encoding="utf-8") as f:
    html_code = f.read()

html_code_updated = html_code.replace("localhost:8000", "localhost:7878")

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_code_updated)

print("✅ index.html updated (API target set to http://localhost:7878).")

# 4. Restart Server on 7878 & Open UI
python_exec = os.path.join(TARGET_DIR, "venv", "Scripts", "python.exe")
if not os.path.exists(python_exec):
    python_exec = sys.executable

print("🔥 Launching FastAPI backend on http://localhost:7878...")
subprocess.Popen([python_exec, os.path.join(TARGET_DIR, "main.py")])

time.sleep(2)
print("🌐 Opening Arena Dashboard in Browser...")
webbrowser.open(f"file:///{os.path.join(TARGET_DIR, 'index.html')}")

print("\n🚀 Done! Arena is now running on port 7878.")