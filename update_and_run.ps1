param(
    [switch]$TestMode,
    [string]$TestRoot,
    [string]$TestCandidatePath,
    [string]$TestCommitSha = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    [switch]$TestFailDependencyInstall,
    [switch]$TestFailAfterSwap
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Repo = "adiatmad/dronetm-progress-mosaic"
$Root = if ($TestMode) { [IO.Path]::GetFullPath($TestRoot) } else { [IO.Path]::GetFullPath($PSScriptRoot) }
if ($TestMode -and (-not $TestRoot -or -not $TestCandidatePath)) { throw "TestMode requires TestRoot and TestCandidatePath." }

$InstallationsRoot = Join-Path $Root ".installations"
$StatePath = Join-Path $Root ".launcher-state.json"
$Required = @("app.py", "gui_app.py", "mosaic_core.py", "requirements.txt", "run_windows.bat")
$PreserveDirs = @("data", ".git", ".venv", ".streamlit", "__pycache__", ".pytest_cache", ".installations")
$PreserveFiles = @(".env", ".env.local", ".launcher-state.json", "current-install.txt", "secrets.toml", "*.tif", "*.tiff", "*.png")
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("dronetm-update-" + [guid]::NewGuid().ToString("N"))
$StageRoot = Join-Path $InstallationsRoot ("staging-" + [guid]::NewGuid().ToString("N"))
$NewRelease = $null
$PointerSwitched = $false
$OldStateExists = Test-Path -LiteralPath $StatePath
$OldStateContent = if ($OldStateExists) { Get-Content -LiteralPath $StatePath -Raw } else { $null }
$OldState = $null
if ($OldStateExists) { try { $OldState = $OldStateContent | ConvertFrom-Json } catch { $OldState = $null } }

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $File $($Arguments -join ' ')" }
}
function Invoke-Robocopy {
    param([string]$Source, [string]$Destination, [string[]]$ExtraExcludeDirs = @())
    $excludeDirs = @($PreserveDirs) + @($ExtraExcludeDirs)
    & robocopy.exe $Source $Destination /MIR /R:2 /W:1 /NFL /NDL /NP /XD $excludeDirs /XF $PreserveFiles
    if ($LASTEXITCODE -gt 7) { throw "robocopy failed with exit code $LASTEXITCODE." }
}
function Invoke-DependencyInstall {
    param([string]$StagePath)
    if ($TestMode) {
        if ($TestFailDependencyInstall) { throw "Injected dependency installation failure for rollback acceptance test." }
        return
    }
    $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if (-not $pyLauncher) { $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue }
    if (-not $pyLauncher) { throw "Python Launcher 'py' was not found. Install 64-bit Python 3.11 or 3.12, then retry." }
    $venvPath = Join-Path $StagePath ".venv"
    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    Write-Host "Creating isolated environment in staging..."
    & $pyLauncher.Source -3.11 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        if (Test-Path -LiteralPath $venvPath) { Remove-Item -LiteralPath $venvPath -Recurse -Force }
        & $pyLauncher.Source -3.12 -m venv $venvPath
        if ($LASTEXITCODE -ne 0) { throw "Could not create a Python 3.11 or 3.12 virtual environment in staging." }
    }
    if (-not (Test-Path -LiteralPath $venvPython)) { throw "Staging virtual environment was not created." }
    Write-Host "Installing staged dependencies..."
    Invoke-Checked -File $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked -File $venvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $StagePath "requirements.txt"))
    Write-Host "Running staged import smoke test..."
    Push-Location $StagePath
    try { Invoke-Checked -File $venvPython -Arguments @("-c", "import numpy, rasterio, requests; import mosaic_core; import gui_app") }
    finally { Pop-Location }
}
function Set-StateAtomically {
    param([string]$Commit, [string]$InstallDirectory)
    $tempState = Join-Path $Root (".launcher-state-" + [guid]::NewGuid().ToString("N") + ".tmp")
    $payload = @{ commit = $Commit; install_dir = $InstallDirectory; updated_utc = [DateTime]::UtcNow.ToString("o") } | ConvertTo-Json
    Set-Content -LiteralPath $tempState -Value $payload -Encoding UTF8
    if (Test-Path -LiteralPath $StatePath) {
        $backupState = Join-Path $Root (".launcher-state-old-" + [guid]::NewGuid().ToString("N") + ".tmp")
        [IO.File]::Replace($tempState, $StatePath, $backupState, $true)
        return $backupState
    }
    [IO.File]::Move($tempState, $StatePath)
    return $null
}
function Restore-OldState {
    if ($OldStateExists) {
        $restorePath = Join-Path $Root (".launcher-state-restore-" + [guid]::NewGuid().ToString("N") + ".tmp")
        Set-Content -LiteralPath $restorePath -Value $OldStateContent -Encoding UTF8
        if (Test-Path -LiteralPath $StatePath) {
            $backupState = Join-Path $Root (".launcher-state-rollback-" + [guid]::NewGuid().ToString("N") + ".tmp")
            [IO.File]::Replace($restorePath, $StatePath, $backupState, $true)
            Remove-Item -LiteralPath $backupState -Force -ErrorAction SilentlyContinue
        } else { [IO.File]::Move($restorePath, $StatePath) }
    } elseif (Test-Path -LiteralPath $StatePath) { Remove-Item -LiteralPath $StatePath -Force }
}

try {
    if (-not $Root) { throw "Could not resolve project root." }
    New-Item -ItemType Directory -Path $Root -Force | Out-Null
    New-Item -ItemType Directory -Path $InstallationsRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null

    $sourceRoot = $null
    if ($TestMode) {
        if ($TestCommitSha -notmatch '^[0-9a-f]{40}$') { throw "Test commit SHA must be exactly 40 lowercase hexadecimal characters." }
        $latestSha = $TestCommitSha
        $sourceRoot = Get-Item -LiteralPath $TestCandidatePath
    } else {
        $headers = @{ "User-Agent" = "dronetm-progress-mosaic-local-launcher"; "Accept" = "application/vnd.github+json" }
        Write-Host "Checking the latest GitHub commit..."
        $commit = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/main" -Headers $headers -TimeoutSec 30
        $latestSha = [string]$commit.sha
        if ($latestSha -notmatch '^[0-9a-f]{40}$') { throw "GitHub returned an invalid commit SHA; refusing to update." }
        if ($OldState -and $OldState.install_dir -match '^release-' -and ([string]$OldState.commit -eq $latestSha)) {
            $releaseName = [string]$OldState.install_dir
            if ($releaseName -notmatch '^(release|previous-legacy)-[A-Za-z0-9-]+$') { throw "Current install pointer is invalid; refusing to launch an unexpected path." }
            $activeRelease = Join-Path $InstallationsRoot $releaseName
            $activePython = Join-Path $activeRelease ".venv\Scripts\python.exe"
            if (-not (Test-Path -LiteralPath $activePython)) { throw "Current release is missing its virtual environment; active files were not modified." }
            Write-Host "Already at commit $latestSha. Launching verified local GUI."
            Push-Location $Root
            try { & $activePython (Join-Path $activeRelease "gui_app.py") } finally { Pop-Location }
            if ($LASTEXITCODE -ne 0) { throw "GUI exited with code $LASTEXITCODE." }
            exit 0
        }
        Write-Host "Downloading archive pinned to commit $latestSha..."
        $zipPath = Join-Path $TempRoot "source.zip"
        $extractPath = Join-Path $TempRoot "extract"
        Invoke-WebRequest -Uri "https://github.com/$Repo/archive/$latestSha.zip" -Headers $headers -OutFile $zipPath -TimeoutSec 180
        Expand-Archive -LiteralPath $zipPath -DestinationPath $extractPath -Force
        $sourceRoot = Get-ChildItem -LiteralPath $extractPath -Directory | Select-Object -First 1
        if (-not $sourceRoot) { throw "GitHub archive was empty." }
    }

    foreach ($name in $Required) {
        if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot.FullName $name) -PathType Leaf)) {
            throw "Pinned archive is missing required file '$name'; active installation was not changed."
        }
    }

    Write-Host "Syncing into a new staging folder, never into the active installation..."
    New-Item -ItemType Directory -Path $StageRoot -Force | Out-Null
    Invoke-Robocopy -Source $sourceRoot.FullName -Destination $StageRoot
    foreach ($name in $Required) {
        if (-not (Test-Path -LiteralPath (Join-Path $StageRoot $name) -PathType Leaf)) { throw "Staging is missing required file '$name'." }
    }

    Invoke-DependencyInstall -StagePath $StageRoot

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    if (-not ($OldState -and $OldState.install_dir)) {
        # One-time migration: preserve a timestamped snapshot of the legacy root install.
        # Keep the original root .venv in place and expose it through a junction in the snapshot.
        $legacyName = "previous-legacy-" + $stamp
        $legacyPath = Join-Path $InstallationsRoot $legacyName
        New-Item -ItemType Directory -Path $legacyPath -Force | Out-Null
        Invoke-Robocopy -Source $Root -Destination $legacyPath -ExtraExcludeDirs @($InstallationsRoot)
        $rootVenv = Join-Path $Root ".venv"
        $legacyVenv = Join-Path $legacyPath ".venv"
        if (Test-Path -LiteralPath $rootVenv -PathType Container) {
            & $env:ComSpec /d /c ('mklink /J "' + $legacyVenv + '" "' + $rootVenv + '"')
            if ($LASTEXITCODE -ne 0) { throw "Could not link the legacy snapshot to the existing .venv; root installation and data remain unchanged." }
        }
        $legacyCommit = if ($OldState -and $OldState.commit) { [string]$OldState.commit } else { "legacy" }
        $OldStateContent = (@{ commit = $legacyCommit; install_dir = $legacyName; updated_utc = [DateTime]::UtcNow.ToString("o") } | ConvertTo-Json)
        $OldStateExists = $true
        $OldState = @{ commit = $legacyCommit; install_dir = $legacyName }
    }

    $releaseName = "release-" + $stamp + "-" + $latestSha
    $NewRelease = Join-Path $InstallationsRoot $releaseName
    if (Test-Path -LiteralPath $NewRelease) { throw "Release path already exists; refusing to overwrite an existing install." }
    Move-Item -LiteralPath $StageRoot -Destination $NewRelease

    $stateBackup = Set-StateAtomically -Commit $latestSha -InstallDirectory $releaseName
    $PointerSwitched = $true
    if ($stateBackup) { Remove-Item -LiteralPath $stateBackup -Force -ErrorAction SilentlyContinue }
    if ($TestFailAfterSwap) { throw "Injected post-swap failure for rollback acceptance test." }

    Write-Host "Verified release activated: $releaseName"
    Write-Host "Timestamped previous releases remain under .installations for rollback."
    Write-Host "Local data/ and source orthophotos remain in the project root. No OpenAerialMap upload or publication is performed."
    if ($TestMode) { exit 0 }

    $activePython = Join-Path $NewRelease ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $activePython)) { throw "Activated release is missing its staged Python environment." }
    Push-Location $Root
    try { & $activePython (Join-Path $NewRelease "gui_app.py") } finally { Pop-Location }
    if ($LASTEXITCODE -ne 0) { throw "GUI exited with code $LASTEXITCODE." }
} catch {
    Write-Host ""
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    if ($PointerSwitched) {
        Write-Host "Restoring the previous install pointer atomically..." -ForegroundColor Yellow
        try { Restore-OldState; Write-Host "Previous install pointer restored." }
        catch { Write-Host ("CRITICAL: pointer rollback failed: " + $_.Exception.Message) -ForegroundColor Red; Write-Host "Do not delete .installations; manually restore .launcher-state.json." }
    } else { Write-Host "Active installation pointer was never changed; the previous install remains active." }
    if ($NewRelease -and (Test-Path -LiteralPath $NewRelease)) { Write-Host "Candidate release retained for inspection: $NewRelease" }
    if (Test-Path -LiteralPath $StageRoot) { Remove-Item -LiteralPath $StageRoot -Recurse -Force -ErrorAction SilentlyContinue }
    if (-not $TestMode) { Write-Host "Press Enter to close."; [void](Read-Host) }
    exit 1
} finally {
    if (Test-Path -LiteralPath $TempRoot) { Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
