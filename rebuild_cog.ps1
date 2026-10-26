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

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
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
$lines.Add('set "HAD_VRT=0"')
$lines.Add('set "HAD_TIF=0"')
$lines.Add('set "NEW_VRT=0"')
$lines.Add('set "NEW_TIF=0"')
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
$lines.Add('echo Candidate COG passed validation. Preparing replacement...')
$lines.Add('if exist "%PROJECT_DIR%\mosaic.vrt" (')
$lines.Add('  move /y "%PROJECT_DIR%\mosaic.vrt" "%PROJECT_DIR%\mosaic.backup-%STAMP%.vrt" >nul')
$lines.Add('  if errorlevel 1 goto :fail')
$lines.Add('  set "HAD_VRT=1"')
$lines.Add(')')
$lines.Add('if exist "%PROJECT_DIR%\mosaic.tif" (')
$lines.Add('  move /y "%PROJECT_DIR%\mosaic.tif" "%PROJECT_DIR%\mosaic.backup-%STAMP%.tif" >nul')
$lines.Add('  if errorlevel 1 goto :rollback')
$lines.Add('  set "HAD_TIF=1"')
$lines.Add(')')
$lines.Add('move /y "%NEXT_VRT%" "%PROJECT_DIR%\mosaic.vrt" >nul')
$lines.Add('if errorlevel 1 goto :rollback')
$lines.Add('set "NEW_VRT=1"')
$lines.Add('move /y "%NEXT_TIF%" "%PROJECT_DIR%\mosaic.tif" >nul')
$lines.Add('if errorlevel 1 goto :rollback')
$lines.Add('set "NEW_TIF=1"')
$lines.Add('echo SUCCESS: validated mosaic.vrt and mosaic.tif replaced. Previous outputs, if any, are archived.')
$lines.Add('echo No source orthophotos were modified. No OAM upload was attempted.')
$lines.Add('exit /b 0')
$lines.Add(':rollback')
$lines.Add('echo ERROR: final output move failed; restoring previous outputs.')
$lines.Add('if "%NEW_VRT%"=="1" if exist "%PROJECT_DIR%\mosaic.vrt" del /q "%PROJECT_DIR%\mosaic.vrt"')
$lines.Add('if "%NEW_TIF%"=="1" if exist "%PROJECT_DIR%\mosaic.tif" del /q "%PROJECT_DIR%\mosaic.tif"')
$lines.Add('if "%HAD_VRT%"=="1" if exist "%PROJECT_DIR%\mosaic.backup-%STAMP%.vrt" move /y "%PROJECT_DIR%\mosaic.backup-%STAMP%.vrt" "%PROJECT_DIR%\mosaic.vrt" >nul')
$lines.Add('if "%HAD_TIF%"=="1" if exist "%PROJECT_DIR%\mosaic.backup-%STAMP%.tif" move /y "%PROJECT_DIR%\mosaic.backup-%STAMP%.tif" "%PROJECT_DIR%\mosaic.tif" >nul')
$lines.Add(':fail')
$lines.Add('echo ERROR: COG rebuild failed. Existing final mosaic.tif was not replaced unless validation succeeded.')
$lines.Add('exit /b 1')
Set-Content -LiteralPath $workerPath -Value $lines -Encoding Default
try {
    Write-Host "Building and validating candidates before touching the final mosaic.tif."
    Write-Host "The VRT candidate is retained for inspection; no OAM upload occurs."
    & $env:ComSpec /d /c ('"' + $workerPath + '"') 2>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) { throw "Build failed with exit code $exitCode. Review $logPath" }
    Write-Host "Finished. Review the mosaic preview and metadata before any publication."
} finally {
    Remove-Item -LiteralPath $workerPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $inputList -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $nextTif) { Remove-Item -LiteralPath $nextTif -Force -ErrorAction SilentlyContinue }
}
