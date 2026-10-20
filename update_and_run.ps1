$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Repo = "adiatmad/dronetm-progress-mosaic"
$Root = [IO.Path]::GetFullPath($PSScriptRoot)
$StatePath = Join-Path $Root ".launcher-state.json"
$Required = @("app.py", "gui_app.py", "mosaic_core.py", "requirements.txt", "run_windows.bat")
$PreserveDirs = @("data", ".venv", ".git", ".streamlit", "__pycache__", ".pytest_cache")
$PreserveFiles = @(".env", ".launcher-state.json")
$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("dronetm-update-" + [guid]::NewGuid().ToString("N"))
$BackupRoot = Join-Path $TempRoot "backup"
$Applied = New-Object System.Collections.Generic.List[string]
$NewFiles = New-Object System.Collections.Generic.List[string]
$Updated = $false

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $File $($Arguments -join ' ')" }
}

try {
    New-Item -ItemType Directory -Path $TempRoot -Force | Out-Null
    $headers = @{ "User-Agent" = "dronetm-progress-mosaic-local-launcher"; "Accept" = "application/vnd.github+json" }
    Write-Host "Checking the latest GitHub commit..."
    $commit = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/commits/main" -Headers $headers -TimeoutSec 30
    $latestSha = [string]$commit.sha
    if ($latestSha -notmatch '^[0-9a-f]{40}$') { throw "GitHub returned an invalid commit SHA; refusing to update." }

    $installedSha = ""
    if (Test-Path -LiteralPath $StatePath) {
        try { $installedSha = [string](Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json).commit } catch { $installedSha = "" }
    }

    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    $needEnvironment = -not (Test-Path -LiteralPath $venvPython)

    if (($installedSha -ne $latestSha) -or !(Test-Path (Join-Path $Root "app.py"))) {
        Write-Host "Updating local application to commit $latestSha ..."
        $zipPath = Join-Path $TempRoot "source.zip"
        $extractPath = Join-Path $TempRoot "extract"
        $archiveUrl = "https://api.github.com/repos/$Repo/zipball/$latestSha"
        Invoke-WebRequest -Uri $archiveUrl -Headers $headers -OutFile $zipPath -TimeoutSec 180
        Expand-Archive -LiteralPath $zipPath -DestinationPath $extractPath -Force
        $sourceRoot = Get-ChildItem -LiteralPath $extractPath -Directory | Select-Object -First 1
        if (-not $sourceRoot) { throw "GitHub archive was empty." }
        foreach ($name in $Required) {
            if (-not (Test-Path -LiteralPath (Join-Path $sourceRoot.FullName $name) -PathType Leaf)) {
                throw "Update archive is missing required file '$name'; no local files were changed."
            }
        }

        $files = Get-ChildItem -LiteralPath $sourceRoot.FullName -File -Recurse | Where-Object {
            $rel = $_.FullName.Substring($sourceRoot.FullName.Length).TrimStart('\','/')
            $parts = $rel -split '[\\/]'
            $skip = $false
            foreach ($part in $parts) { if ($PreserveDirs -contains $part) { $skip = $true; break } }
            if ($PreserveFiles -contains $rel) { $skip = $true }
            if ($_.Extension.ToLowerInvariant() -in @(".tif", ".tiff")) { $skip = $true }
            if ($rel -match '(^|[\\/])\.env($|[\\/])') { $skip = $true }
            -not $skip
        }

        $Updated = $true
        foreach ($file in $files) {
            $rel = $file.FullName.Substring($sourceRoot.FullName.Length).TrimStart('\','/')
            $destination = Join-Path $Root $rel
            $destinationParent = Split-Path -Parent $destination
            New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
            if (Test-Path -LiteralPath $destination -PathType Leaf) {
                $backup = Join-Path $BackupRoot $rel
                New-Item -ItemType Directory -Path (Split-Path -Parent $backup) -Force | Out-Null
                Copy-Item -LiteralPath $destination -Destination $backup -Force
                $Applied.Add($rel)
            } else {
                $NewFiles.Add($rel)
            }
            $stagedFile = Join-Path $TempRoot ("staged-" + [guid]::NewGuid().ToString("N"))
            Copy-Item -LiteralPath $file.FullName -Destination $stagedFile
            Move-Item -LiteralPath $stagedFile -Destination $destination -Force
        }
        $Updated = $true
        $needEnvironment = $true
    } else {
        Write-Host "Application is already at the latest commit ($latestSha)."
    }

    if ($needEnvironment) {
        $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
        if (-not $pyLauncher) { $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue }
        if (-not $pyLauncher) { throw "Python Launcher 'py' was not found. Install 64-bit Python 3.11 or 3.12, then run this launcher again." }
        if (-not (Test-Path -LiteralPath $venvPython)) {
            Write-Host "Creating Python virtual environment..."
            & $pyLauncher.Source -3.11 -m venv $venvPython.Replace("\Scripts\python.exe", "")
            if ($LASTEXITCODE -ne 0) {
                & $pyLauncher.Source -3.12 -m venv $venvPython.Replace("\Scripts\python.exe", "")
                if ($LASTEXITCODE -ne 0) { throw "Could not create a Python 3.11 or 3.12 virtual environment." }
            }
        }
        if (-not (Test-Path -LiteralPath $venvPython)) { throw "Virtual environment was not created." }
        Write-Host "Installing application dependencies..."
        Invoke-Checked -File $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")
        Invoke-Checked -File $venvPython -Arguments @("-m", "pip", "install", "-r", (Join-Path $Root "requirements.txt"))
    }

    if ($Updated -or -not (Test-Path -LiteralPath $StatePath)) {
        $stateTemp = "$StatePath.tmp"
        (@{ commit = $latestSha; updated_utc = [DateTime]::UtcNow.ToString("o") } | ConvertTo-Json) | Set-Content -LiteralPath $stateTemp -Encoding UTF8
        Move-Item -LiteralPath $stateTemp -Destination $StatePath -Force
    }

    $Updated = $false
    Write-Host ""
    Write-Host "Starting native DroneTM Progress Mosaic GUI (no localhost server). Local data folders are preserved."
    Write-Host "This app does not publish to OpenAerialMap automatically."
    Set-Location -LiteralPath $Root
    & $venvPython (Join-Path $Root "gui_app.py")
    if ($LASTEXITCODE -ne 0) { throw "Streamlit exited with code $LASTEXITCODE." }
}
catch {
    Write-Host ""
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    if ($Updated) {
        Write-Host "Rolling back application files changed during this update..." -ForegroundColor Yellow
        foreach ($rel in $Applied) {
            $destination = Join-Path $Root $rel
            $backup = Join-Path $BackupRoot $rel
            if (Test-Path -LiteralPath $backup) {
                New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
                Copy-Item -LiteralPath $backup -Destination $destination -Force
            }
        }
        foreach ($rel in $NewFiles) {
            $destination = Join-Path $Root $rel
            if (Test-Path -LiteralPath $destination -PathType Leaf) { Remove-Item -LiteralPath $destination -Force }
        }
        Write-Host "Application source rollback attempted. Your data/, .venv/, .env, .streamlit/, and GeoTIFFs were excluded from updates."
    }
    Write-Host "Press Enter to close."
    [void](Read-Host)
    exit 1
}
finally {
    if (Test-Path -LiteralPath $TempRoot) { Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue }
}
