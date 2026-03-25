param(
    [switch]$SkipBuild,
    [switch]$ArtifactsOnly
)

# === KONFIGURACJA ===
$VM_IP = "192.168.1.15"                    # IP Twojej VM
$RemoteShareRoot = "\\$VM_IP\agent\DevOPS"
$LocalProject = "C:\Users\Kubiaxx\Documents\Programowanie\DevOPS\my-orciestra"
$DistPath = "$LocalProject\dist"
$ArtifactsPath = "$LocalProject\artifacts"
$ExeName = "agent_service.exe"
$PythonExe = "$LocalProject\env\Scripts\python.exe"

Set-Location $LocalProject

if (-not $SkipBuild) {
    # === 1. BUILD PYINSTALLER ===
    Write-Host ">>> Building with PyInstaller..." -ForegroundColor Yellow
    if (-not (Test-Path $PythonExe)) {
        Write-Host ">>> BUILD FAILED: Python environment not found at $PythonExe" -ForegroundColor Red
        exit 1
    }

    & $PythonExe -c "import PIL; import PyInstaller; print('build_env_ok')"
    if ($LASTEXITCODE -ne 0) {
        Write-Host ">>> Bootstrapping build dependencies in env..." -ForegroundColor Yellow
        & $PythonExe -m pip install Pillow PyInstaller
        if ($LASTEXITCODE -ne 0) {
            Write-Host ">>> BUILD FAILED: unable to install Pillow/PyInstaller in env" -ForegroundColor Red
            exit 1
        }
    }

    & $PythonExe -m PyInstaller --clean agent_service.spec
    if ($LASTEXITCODE -ne 0) {
        Write-Host ">>> BUILD FAILED: PyInstaller returned exit code $LASTEXITCODE" -ForegroundColor Red
        exit 1
    }

    if (-not (Test-Path "$DistPath\$ExeName")) {
        Write-Host ">>> BUILD FAILED!" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host ">>> Skipping build step." -ForegroundColor Yellow
}

# === 2. KOPIUJ PACZKI NA VM ===
Write-Host ">>> Copying dist and artifacts to VM share..." -ForegroundColor Yellow
if (-not (Test-Path $RemoteShareRoot)) {
    Write-Host ">>> COPY FAILED: share not available at $RemoteShareRoot" -ForegroundColor Red
    exit 1
}

$RemoteDistPath = Join-Path $RemoteShareRoot "dist"
$RemoteArtifactsPath = Join-Path $RemoteShareRoot "artifacts"

if (-not $ArtifactsOnly) {
    if (-not (Test-Path $DistPath)) {
        Write-Host ">>> COPY FAILED: dist directory not found at $DistPath" -ForegroundColor Red
        exit 1
    }

    New-Item -ItemType Directory -Force -Path $RemoteDistPath | Out-Null
    Copy-Item "$DistPath\*" -Destination $RemoteDistPath -Recurse -Force
} else {
    Write-Host ">>> Skipping dist copy (ArtifactsOnly)." -ForegroundColor Yellow
}

if (Test-Path $ArtifactsPath) {
    New-Item -ItemType Directory -Force -Path $RemoteArtifactsPath | Out-Null
    Copy-Item "$ArtifactsPath\*" -Destination $RemoteArtifactsPath -Recurse -Force
} else {
    Write-Host ">>> No artifacts directory found at $ArtifactsPath" -ForegroundColor Yellow
}

Write-Host ">>> COPY DONE! Selected payload is on the VM share." -ForegroundColor Green