param(
    [string]$EnvName = "any-auto-register",
    [string]$BindHost = "0.0.0.0",
    [int]$Port = 8000,
    [switch]$RestartExisting = $true
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$conda = Get-Command conda -ErrorAction SilentlyContinue
if (-not $conda) {
    Write-Error "not found conda Order. Please install first Miniconda/Anaconda, and ensure conda Available in Terminal."
    exit 1
}

Write-Host "[INFO] Project directory: $root"
Write-Host "[INFO] use conda environment: $EnvName"
$displayHost = if ($BindHost -eq "0.0.0.0") { "localhost" } else { $BindHost }
Write-Host "[INFO] Start backend: http://$displayHost`:$Port"
Write-Host "[INFO] according to Ctrl+C Can stop service"

if ($RestartExisting) {
    Write-Host "[INFO] Clean old backend before launching / Solver process"
    & "$root\stop_backend.ps1" -BackendPort $Port -SolverPort 8889 -FullStop 0
}

$pythonExe = (conda run --no-capture-output -n $EnvName python -c "import sys; print(sys.executable)").Trim()
if (-not (Test-Path $pythonExe)) {
    Write-Error "Unable to parse conda environment '$EnvName' Corresponding python path."
    exit 1
}

$env:HOST = $BindHost
$env:PORT = [string]$Port

Write-Host "[INFO] Python: $pythonExe"
& $pythonExe main.py
