param(
    [string]$Hostname = "orciestra.lab.local",
    [int]$FrontendPort = 3000,
    [int]$BackendPort = 8765,
    [int]$GuacamolePort = 8088,
    [switch]$DisableGuacamoleProxy,
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

$guacamoleRoute = @"
    @guacamole path /guacamole /guacamole/*
    reverse_proxy @guacamole 127.0.0.1:$GuacamolePort

"@

if ($DisableGuacamoleProxy) {
    $guacamoleRoute = ""
}

$config = @"
{
    local_certs
    admin off
}

$Hostname {
    encode zstd gzip

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "SAMEORIGIN"
        Referrer-Policy "strict-origin-when-cross-origin"
    }

${guacamoleRoute}    @backend path /api/* /frontend /ws
    reverse_proxy @backend 127.0.0.1:$BackendPort

    reverse_proxy 127.0.0.1:$FrontendPort
}
"@

Set-Content -Path $configPath -Value $config -Encoding ASCII

$env:VM_AGENT_SERVER_PUBLIC_URL = "https://$Hostname"

Write-Host "Generated Caddy config: $configPath"
Write-Host "Backend public URL: $($env:VM_AGENT_SERVER_PUBLIC_URL)"
if ($Hostname -ieq "localhost") {
    Write-Host "Using localhost, so no DNS or hosts entry is required."
}
else {
    Write-Host "Remember to point DNS or hosts to this machine for: $Hostname"
}
if ($DisableGuacamoleProxy) {
    Write-Host "Guacamole reverse proxy route is disabled in Caddy. FastAPI can still bridge to an external Guacamole via GUACAMOLE_BASE_URL."
}
else {
    Write-Host "Guacamole stays on http://127.0.0.1:$GuacamolePort and is exposed through https://$Hostname/guacamole/"
}

$caddyExecutablePath = Resolve-CaddyExecutablePath -Executable $CaddyExecutable
if (-not $caddyExecutablePath) {
    throw "Caddy executable '$CaddyExecutable' was not found. Install Caddy or pass -CaddyExecutable with a full path."
}

& $caddyExecutablePath run --config $configPath