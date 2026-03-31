param(
    [string]$Hostname = "localhost",
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 8765,
    [int]$GuacamolePort = 8088,
    [string]$GuacamoleBaseUrl = "",
    [string]$GuacamoleAuthUsername = "",
    [string]$GuacamoleAuthPassword = "",
    [string]$GuacamoleAuthProvider = "",
    [switch]$DisableGuacamoleProxy,
    [switch]$LanHttp,
    [string]$AuthPublicUrl = "",
    [string]$AgentWsUrl = "",
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
$guacamoleBaseUrl = if ($GuacamoleBaseUrl) { $GuacamoleBaseUrl.TrimEnd('/') } else { "http://127.0.0.1:$GuacamolePort/guacamole" }
$guacamoleAuthUsername = if ($GuacamoleAuthUsername) { $GuacamoleAuthUsername } else { [Environment]::GetEnvironmentVariable("GUACAMOLE_AUTH_USERNAME", "Process") }
$guacamoleAuthPassword = if ($GuacamoleAuthPassword) { $GuacamoleAuthPassword } else { [Environment]::GetEnvironmentVariable("GUACAMOLE_AUTH_PASSWORD", "Process") }
$guacamoleAuthProvider = if ($GuacamoleAuthProvider) { $GuacamoleAuthProvider } else { [Environment]::GetEnvironmentVariable("GUACAMOLE_AUTH_PROVIDER", "Process") }

function Test-IsIpv4Literal {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    return $Value.Trim() -match '^(?:\d{1,3}\.){3}\d{1,3}$'
}

function Get-PrimaryLanIPv4 {
    $address = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -and
            $_.IPAddress -notlike '127.*' -and
            $_.PrefixOrigin -ne 'WellKnown'
        } |
        Sort-Object InterfaceMetric, SkipAsSource |
        Select-Object -First 1 -ExpandProperty IPAddress

    return [string]$address
}

$LanHttp = [bool]($LanHttp -or (Test-IsIpv4Literal $Hostname))
$useDirectLanMode = $LanHttp
$publicScheme = if ($useDirectLanMode) { "http" } else { "https" }
$publicPort = if ($useDirectLanMode) { $FrontendPort } else { 443 }
$publicUrl = if ($useDirectLanMode) { "http://${Hostname}:$FrontendPort" } else { "$($publicScheme)://$Hostname" }
$backendPublicUrl = if ($useDirectLanMode) { "http://${Hostname}:$BackendPort" } else { "$($publicScheme)://$Hostname" }
$effectiveAuthPublicUrl = if ($AuthPublicUrl) { $AuthPublicUrl.TrimEnd('/') } else { $backendPublicUrl }
$microsoftCallbackUrl = "$effectiveAuthPublicUrl/api/users/callback/microsoft"
$frontendApiBaseUrl = $effectiveAuthPublicUrl
$frontendWebSocketUrl = if ($frontendApiBaseUrl.StartsWith('https://')) {
    "wss://$($frontendApiBaseUrl.Substring(8))/frontend"
}
elseif ($frontendApiBaseUrl.StartsWith('http://')) {
    "ws://$($frontendApiBaseUrl.Substring(7))/frontend"
}
else {
    "$frontendApiBaseUrl/frontend"
}
$effectiveAgentWsUrl = if ($AgentWsUrl) {
    $AgentWsUrl.TrimEnd('/')
}
elseif ($useDirectLanMode) {
    "ws://${Hostname}:$BackendPort/ws"
}
else {
    ""
}
$publicGuacamoleBaseUrl = if ($DisableGuacamoleProxy) {
    $guacamoleBaseUrl
}
elseif ($AuthPublicUrl) {
    "$effectiveAuthPublicUrl/guacamole"
}
else {
    $guacamoleBaseUrl
}
$serverGuacamoleBaseUrl = $guacamoleBaseUrl
$frontendListenHost = if ($useDirectLanMode) { "0.0.0.0" } else { "127.0.0.1" }
$frontendLoopbackUrl = "http://127.0.0.1:$FrontendPort"
$backendLoopbackUrl = "http://127.0.0.1:$BackendPort"

function ConvertTo-SingleQuotedPowerShellLiteral {
    param([string]$Value)

    if ($null -eq $Value) {
        return "''"
    }

    return "'" + $Value.Replace("'", "''") + "'"
}

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
            if ($useDirectLanMode) {
                Write-Host "Restarting existing frontend process $($frontendProcess.Id) so LAN mode can bind to $frontendListenHost with direct backend URLs."
                Stop-Process -Id $frontendProcess.Id -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 1
                $frontendProcess = $null
            }
            else {
            Write-Host "Frontend already listening on $frontendLoopbackUrl; reusing process $($frontendProcess.Id)."
            return
            }
        }

        throw "Port $FrontendPort is already in use by $($frontendProcess.ProcessName) (PID $($frontendProcess.Id)). Free the port before running start-local.ps1."
    }

    Stop-StaleFrontendInstances

    if (-not (Test-Path $nextCli)) {
        throw "Next.js CLI not found at $nextCli. Run npm install in the frontend first."
    }

    if ($useDirectLanMode) {
        $frontendApiUrlLiteral = ConvertTo-SingleQuotedPowerShellLiteral $frontendApiBaseUrl
        $frontendWsUrlLiteral = ConvertTo-SingleQuotedPowerShellLiteral $frontendWebSocketUrl
        $nextCliLiteral = ConvertTo-SingleQuotedPowerShellLiteral $nextCli
        $frontendRootLiteral = ConvertTo-SingleQuotedPowerShellLiteral $frontendRoot
        $command = @"
Set-Location $frontendRootLiteral
`$env:NEXT_PUBLIC_API_URL = $frontendApiUrlLiteral
`$env:NEXT_PUBLIC_WS_URL = $frontendWsUrlLiteral
& $nextCliLiteral dev --hostname $frontendListenHost --port $FrontendPort
"@
        Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-Command', $command | Out-Null
    }
    else {
        Start-Process -FilePath $nextCli -WorkingDirectory $frontendRoot -ArgumentList 'dev', '--hostname', $frontendListenHost, '--port', "$FrontendPort" | Out-Null
    }

    if (-not (Wait-ForPort -Port $FrontendPort)) {
        throw "Frontend did not start on port $FrontendPort. The script prevents port fallback so local routing stays stable."
    }

    if ($useDirectLanMode) {
        Write-Host "Frontend started on $publicUrl"
    }
    else {
        Write-Host "Frontend started on $frontendLoopbackUrl"
    }
}

function Start-BackendIfNeeded {
    $backendProcess = Get-ListeningProcess -Port $BackendPort
    if ($backendProcess) {
        if ($backendProcess.ProcessName -match "python") {
            if ($useDirectLanMode -or $AuthPublicUrl -or $AgentWsUrl) {
                Write-Host "Restarting existing backend process $($backendProcess.Id) so the public auth URL is applied correctly."
                Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue
                Start-Sleep -Seconds 1
                $backendProcess = $null
            }
            else {
                Write-Host "Backend already listening on http://127.0.0.1:$BackendPort; reusing process $($backendProcess.Id)."
                return
            }
        }

        throw "Port $BackendPort is already in use by $($backendProcess.ProcessName) (PID $($backendProcess.Id)). Free the port before running start-local.ps1."
    }

    if (-not (Test-Path $pythonExe)) {
        throw "Python executable not found at $pythonExe"
    }

    $publicUrlLiteral = ConvertTo-SingleQuotedPowerShellLiteral $effectiveAuthPublicUrl
    $agentWsUrlLiteral = ConvertTo-SingleQuotedPowerShellLiteral $effectiveAgentWsUrl
    $guacamoleBaseUrlLiteral = ConvertTo-SingleQuotedPowerShellLiteral $publicGuacamoleBaseUrl
    $guacamoleServerBaseUrlLiteral = ConvertTo-SingleQuotedPowerShellLiteral $serverGuacamoleBaseUrl
    $guacamoleAuthUsernameLiteral = ConvertTo-SingleQuotedPowerShellLiteral $guacamoleAuthUsername
    $guacamoleAuthPasswordLiteral = ConvertTo-SingleQuotedPowerShellLiteral $guacamoleAuthPassword
    $guacamoleAuthProviderLiteral = ConvertTo-SingleQuotedPowerShellLiteral $guacamoleAuthProvider
    $pythonExeLiteral = ConvertTo-SingleQuotedPowerShellLiteral $pythonExe

    $command = @"
`$env:VM_AGENT_SERVER_PUBLIC_URL = $publicUrlLiteral
if ($agentWsUrlLiteral -ne '') { `$env:VM_AGENT_SERVER_WS_URL = $agentWsUrlLiteral }
`$env:GUACAMOLE_BASE_URL = $guacamoleBaseUrlLiteral
`$env:GUACAMOLE_SERVER_BASE_URL = $guacamoleServerBaseUrlLiteral
if ($guacamoleAuthUsernameLiteral -ne '') { `$env:GUACAMOLE_AUTH_USERNAME = $guacamoleAuthUsernameLiteral }
if ($guacamoleAuthPasswordLiteral -ne '') { `$env:GUACAMOLE_AUTH_PASSWORD = $guacamoleAuthPasswordLiteral }
if ($guacamoleAuthProviderLiteral -ne '') { `$env:GUACAMOLE_AUTH_PROVIDER = $guacamoleAuthProviderLiteral }
& $pythonExeLiteral -m vm_agent_server.src.server
"@
    Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-Command', $command | Out-Null

    if (-not (Wait-ForPort -Port $BackendPort)) {
        throw "Backend did not start on port $BackendPort."
    }

    Write-Host "Backend started on http://127.0.0.1:$BackendPort"
}

function Start-CaddyIfNeeded {
    if ($useDirectLanMode) {
        Write-Host "Skipping Caddy in LAN HTTP mode. Frontend and backend are exposed directly on their own ports."
        return
    }

    $publicProcess = Get-ListeningProcess -Port $publicPort
    if ($publicProcess) {
        if ($publicProcess.ProcessName -ieq "caddy") {
            Write-Host "Caddy is already listening on port $publicPort; restarting process $($publicProcess.Id) so routes match the requested local stack."
            Stop-Process -Id $publicProcess.Id -Force
            Start-Sleep -Seconds 1
        }
        else {
            throw "Port $publicPort is already in use by $($publicProcess.ProcessName) (PID $($publicProcess.Id)). Free the port before running start-local.ps1."
        }
    }

    $disableGuacamoleProxyArg = if ($DisableGuacamoleProxy) { " -DisableGuacamoleProxy" } else { "" }
    $lanHttpArg = if ($LanHttp) { " -LanHttp" } else { "" }
    $command = "& '$caddyScript' -Hostname '$Hostname' -FrontendPort $FrontendPort -BackendPort $BackendPort -GuacamolePort $GuacamolePort$disableGuacamoleProxyArg$lanHttpArg -CaddyExecutable '$CaddyExecutable'"
    Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $command | Out-Null

    if (-not (Wait-ForPort -Port $publicPort)) {
        throw "Caddy did not start on port $publicPort."
    }

    Write-Host "Caddy started on $publicUrl"
}

Write-Host "Launching local stack for $publicUrl"
Write-Host "Guacamole API base URL: $guacamoleBaseUrl"
Write-Host "Guacamole public URL: $publicGuacamoleBaseUrl"
if ($AuthPublicUrl) {
    Write-Host "Microsoft auth callback base URL override: $effectiveAuthPublicUrl"
}
if ($effectiveAgentWsUrl) {
    Write-Host "Agent bootstrap WebSocket URL override: $effectiveAgentWsUrl"
}
if (Test-IsIpv4Literal $Hostname) {
    Write-Host "Detected a raw IPv4 host. LAN HTTP mode was enabled automatically because local HTTPS certificates are not reliable on bare IP addresses."
}
if ($guacamoleAuthUsername) {
    Write-Host "Guacamole API username configured for backend session minting."
}
else {
    Write-Host "Guacamole API username is not configured for this run. Remote workspace launch will stay in diagnostics-only mode."
}
if ($DisableGuacamoleProxy) {
    Write-Host "Caddy will not proxy /guacamole/* in this run. Use this when Guacamole is hosted externally, for example behind Nginx on another machine."
}
elseif ($useDirectLanMode) {
    Write-Host "LAN mode bypasses Caddy entirely. Frontend and backend will talk directly over HTTP."
}
else {
    Write-Host "Caddy will proxy /guacamole/* to local port $GuacamolePort"
}
if ($useDirectLanMode) {
    Write-Host "LAN HTTP mode is enabled. The frontend will listen directly on $publicUrl and the backend on $backendPublicUrl."
    Write-Host "Frontend API base URL: $frontendApiBaseUrl"
    Write-Host "Frontend WebSocket URL: $frontendWebSocketUrl"
}
elseif ($Hostname -ne 'localhost') {
    $lanIp = Get-PrimaryLanIPv4
    if ($lanIp) {
        Write-Host "If another LAN client should resolve this hostname, add this hosts entry on that client:"
        Write-Host "  $lanIp $Hostname"
        Write-Host "Clients also need to trust the Caddy local CA for HTTPS to work cleanly."
    }
}

Start-FrontendIfNeeded
Start-BackendIfNeeded
Start-CaddyIfNeeded

Write-Host ""
Write-Host "Local stack is ready:"
Write-Host "  Frontend: $frontendLoopbackUrl"
Write-Host "  Backend:  $backendLoopbackUrl"
if ($useDirectLanMode) {
    Write-Host "  Public:   $publicUrl"
    Write-Host "  API:      $backendPublicUrl"
}
else {
    Write-Host "  Caddy:    $publicUrl"
}
Write-Host "  Auth:     $effectiveAuthPublicUrl"
Write-Host "  Callback: $microsoftCallbackUrl"
if ($effectiveAgentWsUrl) {
    Write-Host "  Agent WS: $effectiveAgentWsUrl"
}
Write-Host ""
if ($useDirectLanMode) {
    Write-Host "Open the app through $publicUrl. In this mode the frontend uses $frontendApiBaseUrl for API calls and $frontendWebSocketUrl for websocket traffic."
}
else {
    Write-Host "Open the app through $publicUrl, not directly through $frontendLoopbackUrl, otherwise /api requests stay on the Next.js port and return 404."
}
Write-Host ""
if ($DisableGuacamoleProxy) {
    Write-Host "Guacamole does not need to be local for the embedded workspace. FastAPI will use GUACAMOLE_BASE_URL for session minting and tunnel control."
    Write-Host ""
}
if ($useDirectLanMode) {
    Write-Host "LAN HTTP mode is best for local-network testing by IP. Microsoft/Entra callbacks generally require HTTPS, so browser SSO may not work in this mode."
    if ($AuthPublicUrl) {
        Write-Host "Microsoft sign-in will use the separate callback base URL above, while the UI stays on the LAN IP."
    }
}
else {
    Write-Host "To switch later from localhost to your Entra host, rerun this script with -Hostname <your-host> or -AuthPublicUrl <https-url> and register $microsoftCallbackUrl in Entra."
    if ($Hostname -ne 'localhost') {
        Write-Host "For another LAN machine, add a hosts entry there that points $Hostname to this PC's LAN IP."
    }
}

if ($OpenBrowser) {
    Start-Process $publicUrl | Out-Null
}