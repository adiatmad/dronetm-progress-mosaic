$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Prepare one lower-resolution COG for manual OAM upload. Never publish automatically.
$Root = [IO.Path]::GetFullPath($PSScriptRoot)
$InputRaster = Join-Path $Root "data\project_duut-tasi-50m-metinaro\mosaic.tif"
$OutputRaster = Join-Path $Root "data\project_duut-tasi-50m-metinaro\mosaic_oam.tif"
$UploaderUrl = "https://upload.imagery.hotosm.org/"
$ReportedOamLimitBytes = 93 * 1e9
$SafetyLimitBytes = 70 * 1e9
$ScalePercent = 80

if (-not (Test-Path -LiteralPath $InputRaster -PathType Leaf)) {
    $InputRaster = Read-Host "Paste the full path to the existing source mosaic.tif"
}
if (-not (Test-Path -LiteralPath $InputRaster -PathType Leaf)) {
    throw "Source mosaic not found. No output was created."
}
$InputRaster = [IO.Path]::GetFullPath($InputRaster)
$OutputRaster = Join-Path (Split-Path -Parent $InputRaster) "mosaic_oam.tif"
$CandidateRaster = Join-Path (Split-Path -Parent $InputRaster) "mosaic_oam.candidate.tif"
$LogPath = Join-Path (Split-Path -Parent $InputRaster) ("oam_prep_" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".log")

if ($InputRaster -eq $OutputRaster) { throw "Input and output paths must differ." }
if (Test-Path -LiteralPath $OutputRaster) {
    throw "Output already exists: $OutputRaster. Rename or move it yourself before retrying; existing files are never overwritten."
}
if (Test-Path -LiteralPath $CandidateRaster) {
    throw "Candidate already exists: $CandidateRaster. Inspect and remove it manually before retrying."
}

foreach ($tool in @("gdalinfo.exe", "gdal_translate.exe", "gdal.exe")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool was not found. Open OSGeo4W Shell or QGIS/OSGeo4W Shell, then run this command again."
    }
}

function Get-RasterDecodedBytes([string]$Path) {
    $jsonText = & gdalinfo -json $Path 2>&1
    if ($LASTEXITCODE -ne 0) { throw "gdalinfo failed for '$Path': $($jsonText -join [Environment]::NewLine)" }
    $info = ($jsonText -join [Environment]::NewLine) | ConvertFrom-Json
    if (-not $info.size -or -not $info.bands -or $info.bands.Count -lt 1) {
        throw "gdalinfo did not return raster dimensions and bands for '$Path'."
    }
    $bytesPerSample = 0
    foreach ($band in $info.bands) {
        switch -Regex ([string]$band.type) {
            "Byte" { $bytesPerSample += 1; break }
            "UInt16|Int16" { $bytesPerSample += 2; break }
            "UInt32|Int32|Float32|CInt16" { $bytesPerSample += 4; break }
            "UInt64|Int64|Float64|CFloat32" { $bytesPerSample += 8; break }
            "CInt32" { $bytesPerSample += 8; break }
            "CFloat64" { $bytesPerSample += 16; break }
            default { throw "Unsupported or unknown GDAL band type '$($band.type)'; refusing to guess decoded size." }
        }
    }
    return [double]$info.size[0] * [double]$info.size[1] * $bytesPerSample
}

$sourceInfoText = & gdalinfo -json $InputRaster 2>&1
if ($LASTEXITCODE -ne 0) { throw "Cannot inspect source raster: $($sourceInfoText -join [Environment]::NewLine)" }
$sourceInfo = ($sourceInfoText -join [Environment]::NewLine) | ConvertFrom-Json
$sourceBytes = Get-RasterDecodedBytes $InputRaster
$sourceGB = [math]::Round($sourceBytes / 1e9, 2)
Write-Host "Source: $InputRaster"
Write-Host ("Source dimensions: {0} x {1}; bands: {2}; estimated decoded size: {3} GB" -f $sourceInfo.size[0], $sourceInfo.size[1], $sourceInfo.bands.Count, $sourceGB)
Write-Host ("OAM reported limit: 93 GB; local safety threshold: {0} GB." -f [math]::Round($SafetyLimitBytes / 1e9, 2))
Write-Host ("Preparing one COG at {0}% width and height. This reduces linear resolution; original mosaic and source imagery remain untouched." -f $ScalePercent)

try {
    & gdal_translate -of COG -outsize "$ScalePercent%" "$ScalePercent%" -co COMPRESS=DEFLATE -co PREDICTOR=YES -co BIGTIFF=YES -co RESAMPLING=AVERAGE $InputRaster $CandidateRaster 2>&1 |
        Tee-Object -FilePath $LogPath -Append
    if ($LASTEXITCODE -ne 0) { throw "gdal_translate failed (exit $LASTEXITCODE)." }

    & gdal driver cog validate $CandidateRaster 2>&1 | Tee-Object -FilePath $LogPath -Append
    if ($LASTEXITCODE -ne 0) { throw "COG validation failed (exit $LASTEXITCODE)." }

    $candidateBytes = Get-RasterDecodedBytes $CandidateRaster
    $candidateGB = [math]::Round($candidateBytes / 1e9, 2)
    if ($candidateBytes -gt $SafetyLimitBytes) {
        throw "Candidate decoded size is $candidateGB GB, above the $([math]::Round($SafetyLimitBytes / 1e9, 2)) GB safety threshold. Candidate retained for inspection; final output was not created. Adjust scale only after reviewing the log."
    }
    if ($candidateBytes -ge $ReportedOamLimitBytes) {
        throw "Candidate exceeds the reported OAM decoded-size limit. Candidate retained; final output was not created."
    }

    $candidateInfoText = & gdalinfo -json $CandidateRaster 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Could not read candidate metadata." }
    $candidateInfo = ($candidateInfoText -join [Environment]::NewLine) | ConvertFrom-Json
    if ($candidateInfo.bands.Count -ne $sourceInfo.bands.Count) {
        throw "Candidate band count differs from source. Candidate retained; final output was not created."
    }
    if (-not $candidateInfo.coordinateSystem -or -not $candidateInfo.geoTransform) {
        throw "Candidate lacks expected georeferencing metadata. Candidate retained; final output was not created."
    }

    Move-Item -LiteralPath $CandidateRaster -Destination $OutputRaster
    Write-Host ""
    Write-Host "PASS: reduced-resolution COG prepared and validated."
    Write-Host "Output: $OutputRaster"
    Write-Host ("Output dimensions: {0} x {1}; bands: {2}; estimated decoded size: {3} GB" -f $candidateInfo.size[0], $candidateInfo.size[1], $candidateInfo.bands.Count, $candidateGB)
    Write-Host "Original mosaic and task orthophotos were not modified."
    Write-Host "No upload or publishing was performed. Review the reduced-resolution output, then upload it manually."
    Start-Process $UploaderUrl
    Write-Host "Opened official OAM uploader in your browser."
}
catch {
    Write-Error $_
    Write-Host "No upload was attempted. Review log if present: $LogPath"
    exit 1
}
