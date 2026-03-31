param(
    [string]$Hostname = "orciestra.lab.local",
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 8765,
    [int]$GuacamolePort = 8088,
    [switch]$DisableGuacamoleProxy,
    [switch]$LanHttp,
    [string]$CaddyExecutable = "caddy"
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$configPath = Join-Path $repoRoot ".caddy.generated.Caddyfile"

function Resolve-CaddyExecutablePath {
    param([string]$Executable)

    $resolved = Get-Command $Executable -ErrorAction SilentlyContinue
    if ($resolved) {
        return $resolved.Source
    }

    $winGetPackageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $winGetPackageRoot) {
        $wingetBinary = Get-ChildItem $winGetPackageRoot -Recurse -Filter "caddy.exe" -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName
        if ($wingetBinary) {
            return $wingetBinary
        }
    }

    return $null
}

function Test-IsIpv4Literal {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $false
    }

    return $Value.Trim() -match '^(?:\d{1,3}\.){3}\d{1,3}$'
}

$LanHttp = [bool]($LanHttp -or (Test-IsIpv4Literal $Hostname))

$guacamoleRoute = @"
    @guacamole path /guacamole /guacamole/*
    reverse_proxy @guacamole 127.0.0.1:$GuacamolePort

"@

if ($DisableGuacamoleProxy) {
    $guacamoleRoute = ""
}

$siteAddress = if ($LanHttp) { "http://$Hostname" } else { $Hostname }
$strictTransportHeader = if ($LanHttp) { "" } else { '        Strict-Transport-Security "max-age=31536000; includeSubDomains"`r`n' }
$globalOptions = if ($LanHttp) {
@"
{
    admin off
}

"@
}
else {
@"
{
    local_certs
    admin off
}

"@
}

$config = @"
$globalOptions$siteAddress {
    encode zstd gzip

    header {
${strictTransportHeader}        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
    }

${guacamoleRoute}    @backend path /api/* /frontend /ws
    reverse_proxy @backend 127.0.0.1:$BackendPort

    reverse_proxy 127.0.0.1:$FrontendPort
}
"@

Set-Content -Path $configPath -Value $config -Encoding ASCII

$env:VM_AGENT_SERVER_PUBLIC_URL = if ($LanHttp) { "http://$Hostname" } else { "https://$Hostname" }

Write-Host "Generated Caddy config: $configPath"
Write-Host "Backend public URL: $($env:VM_AGENT_SERVER_PUBLIC_URL)"
if ($Hostname -ieq "localhost") {
    Write-Host "Using localhost, so no DNS or hosts entry is required."
}
else {
    Write-Host "Remember to point DNS or hosts to this machine for: $Hostname"
}
if ($LanHttp) {
    Write-Host "LAN HTTP mode is active. Caddy will listen on port 80 without TLS."
}
else {
    Write-Host "TLS uses Caddy local certificates. Remote clients must trust the local Caddy CA."
}
if ($DisableGuacamoleProxy) {
    Write-Host "Guacamole reverse proxy route is disabled in Caddy. FastAPI can still bridge to an external Guacamole via GUACAMOLE_BASE_URL."
}
else {
    $guacamolePublicUrl = if ($LanHttp) { "http://$Hostname/guacamole/" } else { "https://$Hostname/guacamole/" }
    Write-Host "Guacamole stays on http://127.0.0.1:$GuacamolePort and is exposed through $guacamolePublicUrl"
}

$caddyExecutablePath = Resolve-CaddyExecutablePath -Executable $CaddyExecutable
if (-not $caddyExecutablePath) {
    throw "Caddy executable '$CaddyExecutable' was not found. Install Caddy or pass -CaddyExecutable with a full path."
}

& $caddyExecutablePath run --config $configPath
