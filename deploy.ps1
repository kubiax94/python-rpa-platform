# === KONFIGURACJA ===
$ServiceName = "VmAgent"
$VM_IP = "192.168.1.15"                    # IP Twojej VM
$VM_User = "jonko"                           # Użytkownik na VM
$RemotePath = "C:\agent\DevOPS" 
$RemoteLogPath = "C:\VmAgent"             # Ścieżka na VM
$LocalProject = "C:\Users\Kubiaxx\Documents\Programowanie\DevOPS\my-orciestra"
$DistPath = "$LocalProject\dist"
$ExeName = "agent_service.exe"
$PythonExe = "$LocalProject\env\Scripts\python.exe"

# === 1. STOP USŁUGI NA VM ===
Write-Host ">>> Stopping service on VM..." -ForegroundColor Yellow
Invoke-Command -ComputerName $VM_IP -Credential (Get-Credential $VM_User) -ScriptBlock {
    param($svc)
    Stop-Service -Name $svc -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    # Upewnij się że proces nie żyje
    Get-Process -Name "agent_service" -ErrorAction SilentlyContinue | Stop-Process -Force
} -ArgumentList $ServiceName

# === 2. BUILD PYINSTALLER ===
Write-Host ">>> Building with PyInstaller..." -ForegroundColor Yellow
Set-Location $LocalProject
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

# === 3. KOPIUJ NA VM ===
Write-Host ">>> Copying to VM..." -ForegroundColor Yellow
$RemoteShare = "\\$VM_IP\agent\DevOPS\dist"
Copy-Item "$DistPath\$ExeName" -Destination $RemoteShare -Force

# === 4. REINSTALUJ I URUCHOM USŁUGĘ NA VM ===
Write-Host ">>> Reinstalling and starting service on VM..." -ForegroundColor Yellow
Invoke-Command -ComputerName $VM_IP -Credential (Get-Credential $VM_User) -ScriptBlock {
    param($remotePath, $remoteLogPath, $exeName, $svc)
    
    $exeFullPath = "$remotePath\dist\$exeName"
    
    # Usuń starą usługę
    & $exeFullPath remove 2>$null
    Start-Sleep -Seconds 1
    
    # Usuń stary log
    Remove-Item "$remoteLogPath\agent.log" -Force -ErrorAction SilentlyContinue
    
    # Zainstaluj i uruchom
    & $exeFullPath install
    Start-Sleep -Seconds 1
    Start-Service -Name $svc
    
    # Sprawdź status
    Get-Service -Name $svc
} -ArgumentList $RemotePath, $RemoteLogPath, $ExeName, $ServiceName

Write-Host ">>> DEPLOY DONE!" -ForegroundColor Green