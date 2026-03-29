param(
    [string]$Hostname = "localhost",
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 8765,
    [int]$GuacamolePort = 8088,
    [string]$GuacamoleBaseUrl = "",
    [switch]$DisableGuacamoleProxy,
    [string]$CaddyExecutable = "caddy",
    [switch]$OpenBrowser
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendRoot = Join-Path $repoRoot "frontend"
$pythonExe = Join-Path $repoRoot "env\Scripts\python.exe"
$caddyScript = Join-Path $repoRoot "run-caddy.ps1"
$nextCli = Join-Path $frontendRoot "node_modules\.bin\next.cmd"
$nextLockFile = Join-Path $frontendRoot ".next\dev\lock"
$publicUrl = "https://$Hostname"
$guacamoleBaseUrl = if ($GuacamoleBaseUrl) { $GuacamoleBaseUrl.TrimEnd('/') } else { "http://127.0.0.1:$GuacamolePort/guacamole" }

function Get-ListeningProcess {
    param([int]$Port)

    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) {
        return $null
    }

    return Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
}

function Wait-ForPort {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }

    return $false
}

function Stop-StaleFrontendInstances {
    $frontendProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and $_.CommandLine.Contains($frontendRoot) -and $_.CommandLine -match 'next(\.cmd)?\s+dev'
        }

    foreach ($frontendProcess in $frontendProcesses) {
        Stop-Process -Id $frontendProcess.ProcessId -Force -ErrorAction SilentlyContinue
    }

    foreach ($port in ($FrontendPort + 1)..($FrontendPort + 5)) {
        $process = Get-ListeningProcess -Port $port
        if ($process -and $process.ProcessName -ieq "node") {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        }
    }

    if (Test-Path $nextLockFile) {
        Remove-Item $nextLockFile -Force -ErrorAction SilentlyContinue
    }
}

function Start-FrontendIfNeeded {
    $frontendProcess = Get-ListeningProcess -Port $FrontendPort
    if ($frontendProcess) {
        if ($frontendProcess.ProcessName -ieq "node") {
            Write-Host "Frontend already listening on http://127.0.0.1:$FrontendPort; reusing process $($frontendProcess.Id)."
            return
        }

        throw "Port $FrontendPort is already in use by $($frontendProcess.ProcessName) (PID $($frontendProcess.Id)). Free the port before running start-local.ps1."
    }

    Stop-StaleFrontendInstances

    if (-not (Test-Path $nextCli)) {
        throw "Next.js CLI not found at $nextCli. Run npm install in the frontend first."
    }

    Start-Process -FilePath $nextCli -WorkingDirectory $frontendRoot -ArgumentList 'dev', '--hostname', '127.0.0.1', '--port', "$FrontendPort" | Out-Null

    if (-not (Wait-ForPort -Port $FrontendPort)) {
        throw "Frontend did not start on port $FrontendPort. The script prevents port fallback so local routing stays stable."
    }

    Write-Host "Frontend started on http://127.0.0.1:$FrontendPort"
}

function Start-BackendIfNeeded {
    $backendProcess = Get-ListeningProcess -Port $BackendPort
    if ($backendProcess) {
        if ($backendProcess.ProcessName -match "python") {
            Write-Host "Backend already listening on http://127.0.0.1:$BackendPort; reusing process $($backendProcess.Id)."
            return
        }

        throw "Port $BackendPort is already in use by $($backendProcess.ProcessName) (PID $($backendProcess.Id)). Free the port before running start-local.ps1."
    }

    if (-not (Test-Path $pythonExe)) {
        throw "Python executable not found at $pythonExe"
    }

    $command = @"
`$env:VM_AGENT_SERVER_PUBLIC_URL = '$publicUrl'
`$env:GUACAMOLE_BASE_URL = '$guacamoleBaseUrl'
& '$pythonExe' -m vm_agent_server.src.server
"@
    Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-Command', $command | Out-Null

    if (-not (Wait-ForPort -Port $BackendPort)) {
        throw "Backend did not start on port $BackendPort."
    }

    Write-Host "Backend started on http://127.0.0.1:$BackendPort"
}

function Start-CaddyIfNeeded {
    $httpsProcess = Get-ListeningProcess -Port 443
    if ($httpsProcess) {
        if ($httpsProcess.ProcessName -ieq "caddy") {
            Write-Host "Caddy is already listening on port 443; restarting process $($httpsProcess.Id) so routes match the requested local stack."
            Stop-Process -Id $httpsProcess.Id -Force
            Start-Sleep -Seconds 1
        }
        else {
            throw "Port 443 is already in use by $($httpsProcess.ProcessName) (PID $($httpsProcess.Id)). Free the port before running start-local.ps1."
        }
    }

    $disableGuacamoleProxyArg = if ($DisableGuacamoleProxy) { " -DisableGuacamoleProxy" } else { "" }
    $command = "& '$caddyScript' -Hostname '$Hostname' -FrontendPort $FrontendPort -BackendPort $BackendPort -GuacamolePort $GuacamolePort$disableGuacamoleProxyArg -CaddyExecutable '$CaddyExecutable'"
    Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $command | Out-Null

    if (-not (Wait-ForPort -Port 443)) {
        throw "Caddy did not start on port 443."
    }

    Write-Host "Caddy started on $publicUrl"
}

Write-Host "Launching local stack for $publicUrl"
Write-Host "Guacamole API base URL: $guacamoleBaseUrl"
if ($DisableGuacamoleProxy) {
    Write-Host "Caddy will not proxy /guacamole/* in this run. Use this when Guacamole is hosted externally, for example behind Nginx on another machine."
}
else {
    Write-Host "Caddy will proxy /guacamole/* to local port $GuacamolePort"
}

Start-FrontendIfNeeded
Start-BackendIfNeeded
Start-CaddyIfNeeded

Write-Host ""
Write-Host "Local stack is ready:"
Write-Host "  Frontend: http://127.0.0.1:$FrontendPort"
Write-Host "  Backend:  http://127.0.0.1:$BackendPort"
Write-Host "  Caddy:    $publicUrl"
Write-Host ""
Write-Host "Open the app through $publicUrl, not directly through http://127.0.0.1:$FrontendPort, otherwise /api requests stay on the Next.js port and return 404."
Write-Host ""
if ($DisableGuacamoleProxy) {
    Write-Host "Guacamole does not need to be local for the embedded workspace. FastAPI will use GUACAMOLE_BASE_URL for session minting and tunnel control."
    Write-Host ""
}
Write-Host "To switch later from localhost to your Entra host, rerun this script with -Hostname <your-host> and register https://<your-host>/api/users/callback/microsoft in Entra."

if ($OpenBrowser) {
    Start-Process $publicUrl | Out-Null
}