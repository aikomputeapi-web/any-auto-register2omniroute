# Start Backend and Pro Frontend in Dev Mode
Write-Host "[INFO] Starting Backend..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-ExecutionPolicy Bypass", "-File .\start_backend.ps1"

Write-Host "[INFO] Starting Pro Frontend (Vite) on port 5174..." -ForegroundColor Cyan
Set-Location .\frontend_pro
npm run dev
