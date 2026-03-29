param(
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 8765,
    [int]$HttpsPort = 443,
    [switch]$IncludeGuacamole,
    [int]$GuacamolePort = 8088
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendRoot = Join-Path $repoRoot "frontend"
$nextCli = Join-Path $frontendRoot "node_modules\.bin\next.cmd"

function Wait-ForProcessExit {
    param(
        [int[]]$ProcessIds,
        [int]$TimeoutSeconds = 10
    )

    if (-not $ProcessIds -or $ProcessIds.Count -eq 0) {
        return
    }

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $remaining = $ProcessIds | Where-Object {
            Get-Process -Id $_ -ErrorAction SilentlyContinue
        }

        if (-not $remaining -or $remaining.Count -eq 0) {
            return
        }

        Start-Sleep -Milliseconds 300
    }
}

function Stop-ProcessesByCommandLine {
    param(
        [scriptblock]$Predicate,
        [string]$Label
    )

    $matchingProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object $Predicate |
        Sort-Object ProcessId -Unique

    $stoppedProcessIds = @()
    foreach ($matchingProcess in $matchingProcesses) {
        Stop-Process -Id $matchingProcess.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped $Label PID $($matchingProcess.ProcessId)"
        $stoppedProcessIds += $matchingProcess.ProcessId
    }

    Wait-ForProcessExit -ProcessIds $stoppedProcessIds
}

function Stop-ProcessByPort {
    param(
        [int]$Port,
        [string[]]$AllowedProcessNames
    )

    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) {
        Write-Host "Nothing is listening on port $Port"
        return
    }

    $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    if (-not $process) {
        Write-Host "Process on port $Port is already gone"
        return
    }

    if ($AllowedProcessNames -and ($process.ProcessName -notin $AllowedProcessNames)) {
        Write-Host "Skipping port $Port because it belongs to $($process.ProcessName) (PID $($process.Id))"
        return
    }

    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped $($process.ProcessName) on port $Port (PID $($process.Id))"
}

function Stop-FrontendProcesses {
    Stop-ProcessesByCommandLine -Label "frontend host process" -Predicate {
        $_.CommandLine -and $_.CommandLine.Contains($frontendRoot) -and (
            $_.CommandLine -match 'next(\.cmd)?\s+dev' -or
            ($nextCli -and $_.CommandLine.Contains($nextCli)) -or
            $_.Name -ieq 'node.exe' -or
            $_.Name -ieq 'cmd.exe'
        )
    }

    Stop-ProcessByPort -Port $FrontendPort -AllowedProcessNames @("node")

    foreach ($port in ($FrontendPort + 1)..($FrontendPort + 5)) {
        Stop-ProcessByPort -Port $port -AllowedProcessNames @("node")
    }
}

function Stop-BackendProcesses {
    $backendProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and $_.CommandLine.Contains("vm_agent_server.src.server") -and $_.CommandLine.Contains($repoRoot)
        }

    foreach ($backendProcess in $backendProcesses) {
        Stop-Process -Id $backendProcess.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped backend process PID $($backendProcess.ProcessId)"
    }

    Stop-ProcessByPort -Port $BackendPort -AllowedProcessNames @("python", "python.exe")
}

function Stop-CaddyProcesses {
    $caddyProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -ieq "caddy.exe" -or ($_.CommandLine -and $_.CommandLine.Contains("run-caddy.ps1") -and $_.CommandLine.Contains($repoRoot))
        }

    foreach ($caddyProcess in $caddyProcesses) {
        Stop-Process -Id $caddyProcess.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped Caddy-related process PID $($caddyProcess.ProcessId)"
    }

    Stop-ProcessByPort -Port $HttpsPort -AllowedProcessNames @("caddy")
}

Write-Host "Stopping local stack from $repoRoot"

Stop-FrontendProcesses
Stop-BackendProcesses
Stop-CaddyProcesses

if ($IncludeGuacamole) {
    Stop-ProcessByPort -Port $GuacamolePort -AllowedProcessNames @("java", "javaw", "tomcat10", "tomcat9")
}

Write-Host "Local stack stop completed"