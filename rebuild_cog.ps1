$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = [IO.Path]::GetFullPath($PSScriptRoot)
$DefaultOrthophotos = Join-Path $Root "data\project_duut-tasi-50m-metinaro\orthophotos"
$OrthophotosPath = $DefaultOrthophotos
if (-not (Test-Path -LiteralPath $OrthophotosPath -PathType Container)) {
    Write-Host "Default orthophotos folder was not found: $DefaultOrthophotos"
    $OrthophotosPath = Read-Host "Paste the full path to the folder containing task_*.tif files"
}
if (-not (Test-Path -LiteralPath $OrthophotosPath -PathType Container)) { throw "Orthophotos folder does not exist. Nothing was changed." }
$OrthophotosPath = [IO.Path]::GetFullPath($OrthophotosPath)
$SourceFiles = @(Get-ChildItem -LiteralPath $OrthophotosPath -File -Filter "task_*.tif")
if ($SourceFiles.Count -eq 0) { throw "No task_*.tif files found. Nothing was changed." }
$ProjectDir = Split-Path -Parent $OrthophotosPath
$DriveRoot = [IO.Path]::GetPathRoot($ProjectDir)
$Drive = [System.IO.DriveInfo]::new($DriveRoot)
$FreeGiB = [math]::Round($Drive.AvailableFreeSpace / 1GB, 1)
Write-Host ("Found {0} task GeoTIFF(s); {1} GiB free on {2}." -f $SourceFiles.Count, $FreeGiB, $DriveRoot)
if ($Drive.AvailableFreeSpace -lt 60GB) { throw "Less than 60 GiB free. No output files were replaced." }

$envBat = $null
if (-not (Get-Command "gdalbuildvrt.exe" -ErrorAction SilentlyContinue)) {
    $roots = @()
    if ($env:OSGEO4W_ROOT) { $roots += $env:OSGEO4W_ROOT }
    if ($env:ProgramFiles) {
        $roots += Get-ChildItem -LiteralPath $env:ProgramFiles -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like "QGIS*" -or $_.Name -like "OSGeo4W*" } |
            ForEach-Object { $_.FullName }
    }
    $osgeoRoot = Join-Path $env:SystemDrive "OSGeo4W"
    if (Test-Path -LiteralPath $osgeoRoot) { $roots += $osgeoRoot }
    foreach ($candidateRoot in ($roots | Select-Object -Unique)) {
        foreach ($candidate in @((Join-Path $candidateRoot "bin\o4w_env.bat"), (Join-Path $candidateRoot "OSGeo4W.bat"))) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $envBat = $candidate; break }
        }
        if ($envBat) { break }
    }
}
if (-not $envBat -and -not (Get-Command "gdalbuildvrt.exe" -ErrorAction SilentlyContinue)) { throw "GDAL was not found. Open OSGeo4W Shell or install QGIS, then retry." }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
$workerPath = Join-Path ([IO.Path]::GetTempPath()) ("dronetm-rebuild-cog-" + $PID + ".cmd")
$logPath = Join-Path $ProjectDir ("cog_build_" + $stamp + ".log")
$inputList = Join-Path ([IO.Path]::GetTempPath()) ("dronetm-orthophotos-" + $PID + ".txt")
$nextVrt = Join-Path $ProjectDir ("mosaic.next-" + $stamp + ".vrt")
$nextTif = Join-Path $ProjectDir ("mosaic.next-" + $stamp + ".tif")
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("@echo off")
$lines.Add("setlocal")
if ($envBat) { $lines.Add(('call "{0}"' -f $envBat)); $lines.Add('if errorlevel 1 goto :fail') }
$lines.Add(('cd /d "{0}"' -f $OrthophotosPath))
$lines.Add('if errorlevel 1 goto :fail')
$lines.Add(('set "INPUT_LIST={0}"' -f $inputList))
$lines.Add(('set "PROJECT_DIR={0}"' -f $ProjectDir))
$lines.Add(('set "STAMP={0}"' -f $stamp))
$lines.Add(('set "NEXT_VRT={0}"' -f $nextVrt))
$lines.Add(('set "NEXT_TIF={0}"' -f $nextTif))
$lines.Add('dir /b /s /a-d task_*.tif > "%INPUT_LIST%"')
$lines.Add('if errorlevel 1 goto :fail')
$lines.Add('where gdalbuildvrt >nul 2>nul')
$lines.Add('if errorlevel 1 (echo ERROR: gdalbuildvrt is unavailable. & goto :fail)')
$lines.Add('where gdal_translate >nul 2>nul')
$lines.Add('if errorlevel 1 (echo ERROR: gdal_translate is unavailable. & goto :fail)')
$lines.Add('echo Building temporary VRT candidate...')
$lines.Add('gdalbuildvrt -overwrite -strict -resolution average "%NEXT_VRT%" -input_file_list "%INPUT_LIST%"')
$lines.Add('if errorlevel 1 goto :fail')
$lines.Add('echo Creating physical COG candidate...')
$lines.Add('gdal_translate -of COG -co COMPRESS=DEFLATE -co OVERVIEWS=AUTO -co BIGTIFF=YES -co RESAMPLING=AVERAGE "%NEXT_VRT%" "%NEXT_TIF%"')
$lines.Add('if errorlevel 1 goto :fail')
$lines.Add('echo Validating candidate COG...')
$lines.Add('set "VALIDATOR="')
$lines.Add('where validate_cloud_optimized_geotiff.py >nul 2>nul')
$lines.Add('if not errorlevel 1 set "VALIDATOR=validate_cloud_optimized_geotiff.py"')
$lines.Add('if defined VALIDATOR (python "%VALIDATOR%" "%NEXT_TIF%" & if errorlevel 1 goto :fail)')
$lines.Add('if not defined VALIDATOR (')
$lines.Add('  where rio >nul 2>nul')
$lines.Add('  if not errorlevel 1 (rio cogeo validate "%NEXT_TIF%" & if errorlevel 1 goto :fail) else (')
$lines.Add('    where gdal >nul 2>nul')
$lines.Add('    if errorlevel 1 (echo ERROR: no COG validator found. & goto :fail)')
$lines.Add('    gdal driver cog validate "%NEXT_TIF%"')
$lines.Add('    if errorlevel 1 goto :fail')
$lines.Add('  )')
$lines.Add(')')
$lines.Add('echo Candidate COG passed validation.')
$lines.Add('echo Candidates are ready for atomic replacement by the PowerShell wrapper.')
$lines.Add('exit /b 0')
$lines.Add(':fail')
$lines.Add('echo ERROR: candidate build or validation failed. Existing final outputs were untouched.')
$lines.Add('exit /b 1')
Set-Content -LiteralPath $workerPath -Value $lines -Encoding Default
try {
    Write-Host "Building and validating candidates before touching the final mosaic.tif."
    Write-Host "The validated VRT and COG are activated only after validation; no OAM upload occurs."
    & $env:ComSpec /d /c ('"' + $workerPath + '"') 2>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "Build failed with exit code $exitCode. Review $logPath; final outputs were not changed." }

    $finalVrt = Join-Path $ProjectDir "mosaic.vrt"
    $finalTif = Join-Path $ProjectDir "mosaic.tif"
    $vrtBackup = Join-Path $ProjectDir ("mosaic.backup-" + $stamp + ".vrt")
    $tifBackup = Join-Path $ProjectDir ("mosaic.backup-" + $stamp + ".tif")
    $failedVrt = Join-Path $ProjectDir ("mosaic.failed-" + $stamp + ".vrt")
    $failedTif = Join-Path $ProjectDir ("mosaic.failed-" + $stamp + ".tif")
    $hadVrt = Test-Path -LiteralPath $finalVrt
    $hadTif = Test-Path -LiteralPath $finalTif
    $vrtReplaced = $false
    $tifReplaced = $false
    try {
        if ($hadVrt) { [IO.File]::Replace($nextVrt, $finalVrt, $vrtBackup, $true) }
        else { [IO.File]::Move($nextVrt, $finalVrt) }
        $vrtReplaced = $true

        if ($hadTif) { [IO.File]::Replace($nextTif, $finalTif, $tifBackup, $true) }
        else { [IO.File]::Move($nextTif, $finalTif) }
        $tifReplaced = $true
    } catch {
        $commitError = $_.Exception.Message
        try {
            if ($tifReplaced) {
                if ($hadTif -and (Test-Path -LiteralPath $tifBackup)) {
                    [IO.File]::Replace($tifBackup, $finalTif, $failedTif, $true)
                    Remove-Item -LiteralPath $failedTif -Force -ErrorAction SilentlyContinue
                } elseif (-not $hadTif -and (Test-Path -LiteralPath $finalTif)) {
                    Remove-Item -LiteralPath $finalTif -Force
                }
            }
            if ($vrtReplaced) {
                if ($hadVrt -and (Test-Path -LiteralPath $vrtBackup)) {
                    [IO.File]::Replace($vrtBackup, $finalVrt, $failedVrt, $true)
                    Remove-Item -LiteralPath $failedVrt -Force -ErrorAction SilentlyContinue
                } elseif (-not $hadVrt -and (Test-Path -LiteralPath $finalVrt)) {
                    Remove-Item -LiteralPath $finalVrt -Force
                }
            }
        } catch {
            throw "Atomic output replacement failed: $commitError. Automatic restoration also failed: $($_.Exception.Message). Keep all mosaic.backup-* files for manual recovery."
        }
        throw "Atomic output replacement failed; previous outputs were restored: $commitError"
    }
    Write-Host "Validated mosaic.vrt and mosaic.tif activated with atomic file replacement."
    if ($hadVrt) { Write-Host "Previous VRT archived: $vrtBackup" }
    if ($hadTif) { Write-Host "Previous COG archived: $tifBackup" }
    Write-Host "The rebuild does not upload to OpenAerialMap. Review the output before publication."
} finally {
    Remove-Item -LiteralPath $workerPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $inputList -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $nextTif) { Remove-Item -LiteralPath $nextTif -Force -ErrorAction SilentlyContinue }
}
