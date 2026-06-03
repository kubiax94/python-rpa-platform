param(
    [Parameter(Mandatory = $true)]
    [string]$RepoUrl,
    [string]$Ref = "",
    [string]$CheckoutRoot = "",
    [switch]$NoBuild,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

function Test-CommandAvailable {
    param([string]$Name)

    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Resolve-CheckoutRoot {
    param([string]$Value)

    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Value)
    }

    $home = [Environment]::GetFolderPath("UserProfile")
    return (Join-Path $home "source")
}

function Get-RepoDirectoryName {
    param([string]$Url)

    $trimmed = $Url.Trim().TrimEnd('/')
    $lastSegment = $trimmed.Substring($trimmed.LastIndexOf('/') + 1)
    if ($lastSegment.EndsWith('.git')) {
        $lastSegment = $lastSegment.Substring(0, $lastSegment.Length - 4)
    }

    if ([string]::IsNullOrWhiteSpace($lastSegment)) {
        throw "Unable to derive repository directory name from RepoUrl: $Url"
    }

    return $lastSegment
}

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$FailureMessage
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)"
    }
}

if (-not (Test-CommandAvailable "git")) {
    throw "git is required on the target machine"
}

if (-not (Test-CommandAvailable "docker")) {
    throw "docker is required on the target machine"
}

$resolvedCheckoutRoot = Resolve-CheckoutRoot -Value $CheckoutRoot
$repoDirName = Get-RepoDirectoryName -Url $RepoUrl
$repoPath = Join-Path $resolvedCheckoutRoot $repoDirName

New-Item -ItemType Directory -Force -Path $resolvedCheckoutRoot | Out-Null

if (-not (Test-Path $repoPath)) {
    Write-Host ">>> Cloning repository into $repoPath" -ForegroundColor Yellow
    Invoke-Checked -FilePath "git" -ArgumentList @("clone", $RepoUrl, $repoPath) -FailureMessage "git clone failed"
} else {
    Write-Host ">>> Repository already exists at $repoPath" -ForegroundColor Yellow
}

Push-Location $repoPath
try {
    Write-Host ">>> Fetching latest refs" -ForegroundColor Yellow
    Invoke-Checked -FilePath "git" -ArgumentList @("fetch", "--all", "--tags", "--prune") -FailureMessage "git fetch failed"

    if (-not [string]::IsNullOrWhiteSpace($Ref)) {
        Write-Host ">>> Checking out $Ref" -ForegroundColor Yellow
        Invoke-Checked -FilePath "git" -ArgumentList @("checkout", $Ref) -FailureMessage "git checkout failed"

        $remoteBranchExists = (& git ls-remote --heads origin $Ref) | Out-String
        if ($LASTEXITCODE -ne 0) {
            throw "git ls-remote failed (exit code $LASTEXITCODE)"
        }

        if (-not [string]::IsNullOrWhiteSpace($remoteBranchExists)) {
            Write-Host ">>> Pulling latest commits for branch $Ref" -ForegroundColor Yellow
            Invoke-Checked -FilePath "git" -ArgumentList @("pull", "--ff-only", "origin", $Ref) -FailureMessage "git pull failed"
        }
    } else {
        Write-Host ">>> Pulling latest commits for the current default branch" -ForegroundColor Yellow
        Invoke-Checked -FilePath "git" -ArgumentList @("pull", "--ff-only") -FailureMessage "git pull failed"
    }

    if (-not (Test-Path (Join-Path $repoPath "docker-compose.yml"))) {
        throw "docker-compose.yml not found in $repoPath"
    }

    if ($NoStart) {
        Write-Host ">>> Repository is ready at $repoPath" -ForegroundColor Green
        return
    }

    $composeArgs = @("compose", "up", "-d")
    if (-not $NoBuild) {
        $composeArgs += "--build"
    }

    Write-Host ">>> Starting Docker Compose stack" -ForegroundColor Yellow
    Invoke-Checked -FilePath "docker" -ArgumentList $composeArgs -FailureMessage "docker compose up failed"

    Write-Host ">>> Stack is starting. Open http://localhost:8080 or your configured APP_PORT." -ForegroundColor Green
}
finally {
    Pop-Location
}