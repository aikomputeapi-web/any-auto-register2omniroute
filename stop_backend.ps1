param(
    [int]$BackendPort = 8000,
    [int]$SolverPort = 8889,
    [int]$Grok2ApiPort = 8011,
    [int]$CLIProxyAPIPort = 8317,
    [int]$FullStop = 1
)

$ErrorActionPreference = "Stop"
$ports = @($BackendPort, $SolverPort)
if ($FullStop -ne 0) {
    $ports += @($Grok2ApiPort, $CLIProxyAPIPort)
}
$ports = $ports | Where-Object { $_ -gt 0 } | Select-Object -Unique

Write-Host "[INFO] Prepare to stop port: $($ports -join ', ')"

function Get-ProcessIdsByPorts {
    param([int[]]$TargetPorts)
    $result = @()
    $connections = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -in $TargetPorts }
    foreach ($conn in $connections) {
        if ($conn.OwningProcess) {
            $result += [int]$conn.OwningProcess
        }
    }
    return $result | Select-Object -Unique
}

function Get-ProcessIdsByNames {
    param([string[]]$Names)
    $result = @()
    foreach ($name in $Names) {
        try {
            $items = Get-Process -Name $name -ErrorAction SilentlyContinue
            foreach ($item in $items) {
                $result += [int]$item.Id
            }
        } catch {}
    }
    return $result | Select-Object -Unique
}

function Wait-ProcessExit {
    param(
        [int]$ProcessId,
        [int]$TimeoutSeconds = 6
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    return -not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Stop-ProcessTreeSafe {
    param([int]$ProcessId)

    if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
        return $true
    }

    Write-Host "[INFO] Try to stop gracefully PID=$ProcessId"
    try {
        & taskkill.exe /PID $ProcessId /T *> $null
    } catch {
        Write-Warning "taskkill Gracefully stop returning an exception: $($_.Exception.Message)"
    }
    if (Wait-ProcessExit -ProcessId $ProcessId -TimeoutSeconds 6) {
        Write-Host "[OK] Stopped PID=$ProcessId"
        return $true
    }

    Write-Warning "PID=$ProcessId Did not exit at the expected time, forced stop instead"
    try {
        & taskkill.exe /PID $ProcessId /T /F *> $null
    } catch {
        Write-Warning "taskkill Forced stop returns exception: $($_.Exception.Message)"
    }
    if (Wait-ProcessExit -ProcessId $ProcessId -TimeoutSeconds 6) {
        Write-Host "[OK] Forced to stop PID=$ProcessId"
        return $true
    }

    Write-Warning "taskkill failed to stop completely PID=$ProcessId, try using Stop-Process -Force"
    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
    } catch {
        Write-Warning "Stop-Process -Force fail: $($_.Exception.Message)"
    }
    if (Wait-ProcessExit -ProcessId $ProcessId -TimeoutSeconds 6) {
        Write-Host "[OK] Passed Stop-Process Forced stop PID=$ProcessId"
        return $true
    }

    Write-Warning "PID=$ProcessId Stop failed"
    return $false
}

$connections = Get-ProcessIdsByPorts -TargetPorts $ports
$extraNames = @()
if ($FullStop -ne 0) {
    $extraNames += @("KiroAccountManager", "kiro-account-manager")
}
$extraPids = Get-ProcessIdsByNames -Names $extraNames
$targets = @($connections + $extraPids) | Where-Object { $_ } | Select-Object -Unique

if (-not $targets) {
    Write-Host "[INFO] No process found that needs to be stopped"
    exit 0
}

foreach ($procId in $targets) {
    try {
        Stop-ProcessTreeSafe -ProcessId $procId | Out-Null
    } catch {
        Write-Warning "stop PID=$procId fail: $($_.Exception.Message)"
    }
}

Write-Host "[INFO] stop completion"
