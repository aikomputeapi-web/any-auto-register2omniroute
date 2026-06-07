# Start Backend and AI Frontend in Dev Mode
Write-Host "[INFO] Starting Backend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy Bypass", "-File .\start_backend.ps1"

Write-Host "[INFO] Starting AI Frontend (Vite) on port 5173..." -ForegroundColor Cyan
Set-Location .\frontend
npm run dev
