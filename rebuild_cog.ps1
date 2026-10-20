$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$Root = [IO.Path]::GetFullPath($PSScriptRoot)
$DefaultOrthophotos = Join-Path $Root "data\project_duut-tasi-50m-metinaro\orthophotos"
$OrthophotosPath = $DefaultOrthophotos

if (-not (Test-Path -LiteralPath $OrthophotosPath -PathType Container)) {
    Write-Host "Default orthophotos folder was not found:"
    Write-Host "  $DefaultOrthophotos"
    $OrthophotosPath = Read-Host "Paste the full path to the folder containing task_*.tif files"
}
if (-not (Test-Path -LiteralPath $OrthophotosPath -PathType Container)) {
    Write-Error "Orthophotos folder does not exist. Nothing was changed."
    exit 1
}
$OrthophotosPath = [IO.Path]::GetFullPath($OrthophotosPath)
$SourceFiles = @(Get-ChildItem -LiteralPath $OrthophotosPath -File -Filter "task_*.tif")
if ($SourceFiles.Count -eq 0) {
    Write-Error "No task_*.tif files found in '$OrthophotosPath'. Nothing was changed."
    exit 1
}

$ProjectDir = Split-Path -Parent $OrthophotosPath
$DriveRoot = [IO.Path]::GetPathRoot($ProjectDir)
$Drive = New-Object System.IO.DriveInfo($DriveRoot)
$FreeGiB = [math]::Round($Drive.AvailableFreeSpace / 1GB, 1)
Write-Host ("Found {0} task GeoTIFF(s)." -f $SourceFiles.Count)
Write-Host ("Output folder: {0}" -f $ProjectDir)
Write-Host ("Free space on {0}: {1} GiB" -f $DriveRoot, $FreeGiB)
if ($Drive.AvailableFreeSpace -lt 60GB) {
    Write-Error "Less than 60 GiB free. This is a minimum safety gate, not a guarantee of sufficient space. No output files were replaced."
    exit 1
}

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
        foreach ($candidate in @(
            (Join-Path $candidateRoot "bin\o4w_env.bat"),
            (Join-Path $candidateRoot "OSGeo4W.bat")
        )) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { $envBat = $candidate; break }
        }
        if ($envBat) { break }
    }
}
if (-not $envBat -and -not (Get-Command "gdalbuildvrt.exe" -ErrorAction SilentlyContinue)) {
    Write-Error "GDAL was not found in PATH and no OSGeo4W/QGIS environment script was found in common installation folders. Open OSGeo4W Shell or install QGIS, then retry. No outputs were replaced."
    exit 1
}
if ($envBat) { Write-Host "Using GDAL environment: $envBat" }

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$workerPath = Join-Path ([IO.Path]::GetTempPath()) ("dronetm-rebuild-cog-" + $PID + ".cmd")
$logPath = Join-Path $ProjectDir ("cog_build_" + $stamp + ".log")
$inputList = Join-Path ([IO.Path]::GetTempPath()) ("dronetm-orthophotos-" + $PID + ".txt")
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("@echo off")
$lines.Add("setlocal")
if ($envBat) { $lines.Add(('call "{0}"' -f $envBat)); $lines.Add('if errorlevel 1 goto :fail') }
$lines.Add(('cd /d "{0}"' -f $OrthophotosPath))
$lines.Add('if errorlevel 1 goto :fail')
$lines.Add(('set "INPUT_LIST={0}"' -f $inputList))
$lines.Add(('set "PROJECT_DIR={0}"' -f $ProjectDir))
$lines.Add(('set "STAMP={0}"' -f $stamp))
$lines.Add('set "HAD_VRT=0"')
$lines.Add('set "HAD_TIF=0"')
$lines.Add('set "NEW_VRT=0"')
$lines.Add('set "NEW_TIF=0"')
$lines.Add('set "NEW_VRT=0"')
$lines.Add('set "NEW_TIF=0"')
$lines.Add('dir /b /s /a-d task_*.tif > "%INPUT_LIST%"')
$lines.Add('if errorlevel 1 goto :fail')
$lines.Add('for %%F in ("%INPUT_LIST%") do if %%~zF LEQ 0 goto :fail')
$lines.Add('where gdalbuildvrt >nul 2>nul')
$lines.Add('if errorlevel 1 (echo ERROR: gdalbuildvrt is unavailable. & goto :fail)')
$lines.Add('where gdal_translate >nul 2>nul')
$lines.Add('if errorlevel 1 (echo ERROR: gdal_translate is unavailable. & goto :fail)')
$lines.Add('where gdal >nul 2>nul')
$lines.Add('if errorlevel 1 (echo ERROR: GDAL command-line interface is unavailable. & goto :fail)')
$lines.Add('echo Building strict virtual mosaic candidate...')
$lines.Add('if exist "%PROJECT_DIR%\mosaic.next.vrt" del /q "%PROJECT_DIR%\mosaic.next.vrt"')
$lines.Add('if exist "%PROJECT_DIR%\mosaic.next.tif" del /q "%PROJECT_DIR%\mosaic.next.tif"')
$lines.Add('gdalbuildvrt -overwrite -strict -resolution average "%PROJECT_DIR%\mosaic.next.vrt" -input_file_list "%INPUT_LIST%"')
$lines.Add('if errorlevel 1 goto :fail')
$lines.Add('echo Creating physical COG candidate...')
$lines.Add('gdal_translate -of COG -co COMPRESS=DEFLATE -co PREDICTOR=YES -co BIGTIFF=YES -co RESAMPLING=AVERAGE "%PROJECT_DIR%\mosaic.next.vrt" "%PROJECT_DIR%\mosaic.next.tif"')
$lines.Add('if errorlevel 1 goto :fail')
$lines.Add('echo Validating candidate COG...')
$lines.Add('gdal driver cog validate "%PROJECT_DIR%\mosaic.next.tif"')
$lines.Add('if errorlevel 1 goto :fail')
$lines.Add('echo Candidate validated. Replacing final outputs; previous outputs are retained as backups.')
$lines.Add('if exist "%PROJECT_DIR%\mosaic.vrt" (move /y "%PROJECT_DIR%\mosaic.vrt" "%PROJECT_DIR%\mosaic.backup-%STAMP%.vrt" >nul & if errorlevel 1 goto :rollback & set "HAD_VRT=1")')
$lines.Add('if exist "%PROJECT_DIR%\mosaic.tif" (move /y "%PROJECT_DIR%\mosaic.tif" "%PROJECT_DIR%\mosaic.backup-%STAMP%.tif" >nul & if errorlevel 1 goto :rollback & set "HAD_TIF=1")')
$lines.Add('move /y "%PROJECT_DIR%\mosaic.next.vrt" "%PROJECT_DIR%\mosaic.vrt" >nul')
$lines.Add('if errorlevel 1 goto :rollback')
$lines.Add('set "NEW_VRT=1"')
$lines.Add('move /y "%PROJECT_DIR%\mosaic.next.tif" "%PROJECT_DIR%\mosaic.tif" >nul')
$lines.Add('if errorlevel 1 goto :rollback')
$lines.Add('set "NEW_TIF=1"')
$lines.Add('del /q "%INPUT_LIST%" >nul 2>nul')
$lines.Add('echo SUCCESS: validated mosaic.vrt and mosaic.tif were created.')
$lines.Add('echo COG: "%PROJECT_DIR%\mosaic.tif"')
$lines.Add('echo VRT: "%PROJECT_DIR%\mosaic.vrt"')
$lines.Add('echo No source orthophotos were modified. No upload was attempted.')
$lines.Add('exit /b 0')
$lines.Add(':rollback')
$lines.Add('echo ERROR: output replacement failed; attempting to restore previous outputs.')
$lines.Add('if "%NEW_VRT%"=="1" if exist "%PROJECT_DIR%\mosaic.vrt" del /q "%PROJECT_DIR%\mosaic.vrt"')
$lines.Add('if "%NEW_TIF%"=="1" if exist "%PROJECT_DIR%\mosaic.tif" del /q "%PROJECT_DIR%\mosaic.tif"')
$lines.Add('if "%HAD_VRT%"=="1" if exist "%PROJECT_DIR%\mosaic.backup-%STAMP%.vrt" move /y "%PROJECT_DIR%\mosaic.backup-%STAMP%.vrt" "%PROJECT_DIR%\mosaic.vrt" >nul')
$lines.Add('if "%HAD_TIF%"=="1" if exist "%PROJECT_DIR%\mosaic.backup-%STAMP%.tif" move /y "%PROJECT_DIR%\mosaic.backup-%STAMP%.tif" "%PROJECT_DIR%\mosaic.tif" >nul')
$lines.Add(':fail')
$lines.Add('del /q "%INPUT_LIST%" >nul 2>nul')
$lines.Add('echo ERROR: mosaic build failed. Existing final outputs were not intentionally replaced before COG validation.')
$lines.Add('exit /b 1')
Set-Content -LiteralPath $workerPath -Value $lines -Encoding Default

Write-Host ""
Write-Host "This process rebuilds from local task_*.tif files only."
Write-Host "It does not download imagery and does not upload to OpenAerialMap."
Write-Host "Overlap handling is GDAL VRT source priority, not alpha-aware blending."
Write-Host "Build log: $logPath"
Write-Host ""

try {
    & $env:ComSpec /d /c ('"' + $workerPath + '"') 2>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-Host "Build failed. Review log: $logPath" -ForegroundColor Red
        exit $exitCode
    }
    Write-Host ""
    Write-Host "Finished. Review the preview and metadata before any publication."
}
finally {
    Remove-Item -LiteralPath $workerPath -Force -ErrorAction SilentlyContinue
}
