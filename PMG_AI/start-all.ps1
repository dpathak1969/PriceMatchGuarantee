# start-all.ps1 - one command to run the whole system on Windows (development mode).
#   ML endpoint (Flask/waitress) :5001  ->  Node backend :4000  ->  React dev server :5173
# Usage:  .\start-all.ps1          (from the PMG_AI folder)   Stop with Ctrl+C in each window or close them.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$py   = Join-Path $root 'VENV_PMG\Scripts\python.exe'          # the project's virtual environment

# Re-read PATH from the registry: if Node.js was installed after this terminal/VS Code was opened,
# the running session still has the OLD PATH and `npm` would be "not recognized". The three windows
# started below inherit this refreshed PATH.
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Write-Error 'Node.js/npm not found. Install it (winget install OpenJS.NodeJS.LTS) and re-run.'; exit 1
}

# 1) ML endpoint first: the backend checks it on /api/health
Start-Process powershell -ArgumentList '-NoExit', '-Command', "& '$py' '$root\ml_service\serve.py'"
# 2) Node backend (reads backend\.env if present)
Start-Process powershell -ArgumentList '-NoExit', '-Command', "cd '$root\backend'; npm start"
# 3) React dev server with hot reload
Start-Process powershell -ArgumentList '-NoExit', '-Command', "cd '$root\frontend'; npm run dev"

Write-Host 'Starting... open http://localhost:5173  (health: http://localhost:4000/api/health)'
