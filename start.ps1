# 1. Force directory to your project folder
Set-Location -Path "C:\Projects\AI_Agent_Test"

# 2. Kill any old background python server instances
Get-Process python -ErrorAction SilentlyContinue | Where-Object {$_.Path -like "*AI_Agent_Test*"} | Stop-Process -Force

# 3. Start main.py directly using your project's virtual environment
Start-Process -FilePath "C:\Projects\AI_Agent_Test\venv\Scripts\python.exe" -ArgumentList "main.py" -WorkingDirectory "C:\Projects\AI_Agent_Test"

# Wait for server to initialize
Start-Sleep -Seconds 3

# 4. Open the UI via the local server (prevents CORS and protocol issues)
Start-Process "http://localhost:7878"
