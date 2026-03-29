param(
    [string]$DbPath = "server_settings.db",
    [string]$RowId = "server-settings",
    [string]$ClientSecret
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$resolvedDbPath = if ([System.IO.Path]::IsPathRooted($DbPath)) { $DbPath } else { Join-Path $repoRoot $DbPath }
$pythonExe = Join-Path $repoRoot "env\Scripts\python.exe"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe"
}

if (-not (Test-Path $resolvedDbPath)) {
    throw "Server settings database not found at $resolvedDbPath"
}

if (-not $ClientSecret) {
    $secureSecret = Read-Host "Enter Microsoft Entra client secret" -AsSecureString
    $marshal = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
    try {
        $ClientSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($marshal)
    }
    finally {
        if ($marshal -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($marshal)
        }
    }
}

if ([string]::IsNullOrWhiteSpace($ClientSecret)) {
    throw "Client secret cannot be empty"
}

$backupPath = "$resolvedDbPath.pre-client-secret.bak"
Copy-Item $resolvedDbPath $backupPath -Force

$command = @"
import json
import sqlite3
import sys

db_path = sys.argv[1]
row_id = sys.argv[2]
client_secret = sys.argv[3]

conn = sqlite3.connect(db_path)
row = conn.execute("SELECT payload_json FROM server_settings WHERE id = ?", (row_id,)).fetchone()
if not row or not row[0]:
    raise SystemExit("No server settings row found")

payload = json.loads(row[0])
identity = payload.setdefault("identity", {})
azure = identity.setdefault("azure", {})
azure["client_secret"] = client_secret

conn.execute(
    "UPDATE server_settings SET payload_json = ? WHERE id = ?",
    (json.dumps(payload, ensure_ascii=True), row_id),
)
conn.commit()
conn.close()
"@

@($command) | & $pythonExe - $resolvedDbPath $RowId $ClientSecret

if ($LASTEXITCODE -ne 0) {
    throw "Failed to update Entra client secret in the database"
}

Write-Host "Updated Entra client secret in $resolvedDbPath"
Write-Host "Backup created at $backupPath"
Write-Host "Restart the backend to load the updated settings snapshot"