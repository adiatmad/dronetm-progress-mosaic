# Spec: One-click local updater and raster preparation

## Goal
Provide independent Windows workflows for the local DroneTM Progress Mosaic repository:
1. Update the app from the latest `main` commit and launch it.
2. Rebuild `mosaic.vrt` and a physical COG `mosaic.tif` from existing local orthophotos.
3. Prepare one reduced-resolution COG from the existing mosaic for manual OAM upload.

## Constraints
- Never upload or publish to OpenAerialMap automatically.
- Never modify or delete source `task_*.tif` files.
- Preserve local `data/`, virtual environment, credentials, and local application outputs during app updates.
- Do not replace final mosaic outputs until a candidate COG validates.
- OAM preparation must read the existing mosaic, write a separate `mosaic_oam.tif`, and never overwrite an existing output.
- Estimate decoded raster bytes from dimensions, band count, and sample types; require the output to be at most 70 GB decimal, below the reported 93 GB OAM limit.
- Preserve georeferencing and band count; validate COG structure before creating the final output.
- Open the official OAM uploader only after local validation. Never submit credentials, upload files, or publish from the script.
- Do not report a successful build/update when a command fails.
- Do not describe default VRT source priority as alpha-aware blending.
- Windows launchers must invoke PowerShell by its full system path rather than relying on PATH.

## Acceptance criteria
- [ ] Existing updater and COG rebuild behavior remains intact.
- [ ] OAM preparation accepts the default local mosaic or prompts for a source path.
- [ ] OAM preparation writes a separate output at 80% width and height, preserving geographic extent and georeferencing.
- [ ] The original mosaic and all task orthophotos remain untouched.
- [ ] Candidate COG validation, band-count/georeferencing checks, and decoded-size safety checks pass before finalizing.
- [ ] Output decoded size must be no more than 70 GB decimal and below the reported 93 GB limit.
- [ ] Existing output/candidate files are not silently overwritten.
- [ ] The official uploader opens only after successful local validation; no upload or publishing is automated.
- [ ] Existing Python tests and launcher-contract tests pass in CI.
- [ ] Windows manual acceptance verifies a small disposable raster, metadata, decoded-size gate, and output preservation.

## Known limitations
The GDAL VRT mosaic uses standard source priority for overlaps; it is not alpha-aware blending. The 80% scale is an initial conservative setting, but validation—not the scale assumption—decides whether the result is small enough. Review the reduced-resolution output before upload.
