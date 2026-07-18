# PowerShell script to run the HP Laptop Subscription flow
# This launches the debugger Chrome, starts the CDP bridge, and runs the HP registration script.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$parent = Split-Path $root -Parent
$devtoolsDir = Join-Path $parent "devtools-inspector"

Write-Host "[INFO] Starting Remote-Debugging Chrome..." -ForegroundColor Green
$ChromeJob = Start-Process "node" -ArgumentList "src/launch-chrome.js", "--url", "https://hplaptopsubscription.hp.com" -WorkingDirectory $devtoolsDir -PassThru -WindowStyle Hidden

Write-Host "[INFO] Starting CDP Bridge Server..." -ForegroundColor Green
$BridgeJob = Start-Process "npm" -ArgumentList "start" -WorkingDirectory $devtoolsDir -PassThru -WindowStyle Hidden

Write-Host "[INFO] Waiting 5 seconds for bridge connection to establish..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# Verify connection status using REST API
try {
    $status = Invoke-RestMethod -Uri "http://localhost:3005/status" -ErrorAction SilentlyContinue
    if ($status -and $status.connected -eq $true) {
        Write-Host "[OK] Connected to Chrome on port $($status.port)" -ForegroundColor Green
    } else {
        # Try triggering connection explicitly
        $conn = Invoke-RestMethod -Method POST -Uri "http://localhost:3005/connect" -ErrorAction SilentlyContinue
        Write-Host "[INFO] Triggered bridge connect request: $conn" -ForegroundColor Yellow
    }
} catch {
    Write-Host "[WARN] Could not contact bridge API. It may still be starting up." -ForegroundColor Red
}

Write-Host "[INFO] Running HP Registration Script..." -ForegroundColor Green
if (Test-Path "$root\pro_account_register\register_hp.py") {
    python "$root\pro_account_register\register_hp.py"
} else {
    python "$root\register_hp.py"
}

Write-Host "[INFO] Flow run complete." -ForegroundColor Green
