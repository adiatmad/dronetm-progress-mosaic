$ErrorActionPreference = "Stop"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$updater = Join-Path $repoRoot "update_and_run.ps1"
$temp = Join-Path ([IO.Path]::GetTempPath()) ("dronetm-updater-rollback-test-" + [guid]::NewGuid().ToString("N"))
$root = Join-Path $temp "install-root"
$candidate = Join-Path $temp "candidate"
$installations = Join-Path $root ".installations"
$oldReleaseName = "release-old-0000000000000000000000000000000000000000"
$oldRelease = Join-Path $installations $oldReleaseName
$statePath = Join-Path $root ".launcher-state.json"
$sha = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

function Assert([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
try {
    New-Item -ItemType Directory -Path $oldRelease -Force | Out-Null
    New-Item -ItemType Directory -Path $candidate -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $root "data") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $oldRelease "active.txt") -Value "old-release"
    Set-Content -LiteralPath (Join-Path $candidate "app.py") -Value "candidate"
    Set-Content -LiteralPath (Join-Path $candidate "gui_app.py") -Value "candidate"
    Set-Content -LiteralPath (Join-Path $candidate "mosaic_core.py") -Value "candidate"
    Set-Content -LiteralPath (Join-Path $candidate "requirements.txt") -Value "test"
    Set-Content -LiteralPath (Join-Path $candidate "run_windows.bat") -Value "test"
    Set-Content -LiteralPath (Join-Path $root "data\keep.txt") -Value "must-survive"
    @{ commit = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; install_dir = $oldReleaseName } | ConvertTo-Json | Set-Content -LiteralPath $statePath

    $dependencyOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $updater -TestMode -TestRoot $root -TestCandidatePath $candidate -TestCommitSha $sha -TestFailDependencyInstall 2>&1
    $dependencyExit = $LASTEXITCODE
    Assert ($dependencyExit -ne 0) "Injected dependency failure unexpectedly succeeded."
    Assert (($dependencyOutput -join "`n") -match "Injected dependency installation failure") "Dependency failure injection did not reach the intended step."
    $afterDependencyFailure = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    Assert ($afterDependencyFailure.install_dir -eq $oldReleaseName) "Dependency failure changed the active install pointer."
    Assert ((Get-Content -LiteralPath (Join-Path $oldRelease "active.txt") -Raw).Trim() -eq "old-release") "Previous install content changed after dependency failure."
    Assert ((Get-Content -LiteralPath (Join-Path $root "data\keep.txt") -Raw).Trim() -eq "must-survive") "Local data was changed during staging."

    $swapOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $updater -TestMode -TestRoot $root -TestCandidatePath $candidate -TestCommitSha $sha -TestFailAfterSwap 2>&1
    $swapExit = $LASTEXITCODE
    Assert ($swapExit -ne 0) "Injected post-swap failure unexpectedly succeeded."
    Assert (($swapOutput -join "`n") -match "Injected post-swap failure") "Post-swap failure injection did not reach the intended step."
    Assert (($swapOutput -join "`n") -match "Previous install pointer restored") "The updater did not report successful pointer restoration."
    $afterPostSwapFailure = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    Assert ($afterPostSwapFailure.install_dir -eq $oldReleaseName) "Post-swap failure did not restore the prior install pointer."
    Assert ((Get-Content -LiteralPath (Join-Path $oldRelease "active.txt") -Raw).Trim() -eq "old-release") "Previous install content changed after pointer rollback."
    Assert ((Get-Content -LiteralPath (Join-Path $root "data\keep.txt") -Raw).Trim() -eq "must-survive") "Local data did not survive rollback."
    # Exercise the successful first-migration path in a fresh synthetic install root.
    $freshRoot = Join-Path $temp "fresh-install-root"
    New-Item -ItemType Directory -Path (Join-Path $freshRoot "data") -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $freshRoot "legacy-app.txt") -Value "legacy-install"
    Set-Content -LiteralPath (Join-Path $freshRoot "data\keep.txt") -Value "fresh-data-must-survive"
    $freshOutput = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $updater -TestMode -TestRoot $freshRoot -TestCandidatePath $candidate -TestCommitSha $sha 2>&1
    $freshExit = $LASTEXITCODE
    Assert ($freshExit -eq 0) ("Successful first migration failed: " + ($freshOutput -join "`n"))
    $freshState = Get-Content -LiteralPath (Join-Path $freshRoot ".launcher-state.json") -Raw | ConvertFrom-Json
    Assert ($freshState.install_dir -like "release-*") "Successful migration did not activate a release pointer."
    Assert ((Test-Path -LiteralPath (Join-Path $freshRoot (".installations\" + $freshState.install_dir + "\gui_app.py")))) "Activated release is missing the staged GUI."
    $legacySnapshots = @(Get-ChildItem -LiteralPath (Join-Path $freshRoot ".installations") -Directory -Filter "previous-legacy-*")
    Assert ($legacySnapshots.Count -eq 1) "First migration did not preserve exactly one timestamped legacy snapshot."
    Assert ((Get-Content -LiteralPath (Join-Path $legacySnapshots[0].FullName "legacy-app.txt") -Raw).Trim() -eq "legacy-install") "Legacy snapshot did not preserve the pre-update root files."
    Assert ((Get-Content -LiteralPath (Join-Path $freshRoot "data\keep.txt") -Raw).Trim() -eq "fresh-data-must-survive") "First migration changed local data."

    Write-Host "PASS: dependency-failure/post-swap rollback and successful first migration preserve prior files and local data."
    $global:LASTEXITCODE = 0
} finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
}
