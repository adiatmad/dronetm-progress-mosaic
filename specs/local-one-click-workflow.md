# Spec: One-click local updater and COG rebuild

## Goal
Provide two independent Windows double-click workflows for the local DroneTM Progress Mosaic repository:
1. Update the app from the latest \`main\` commit and launch it.
2. Rebuild \`mosaic.vrt\` and a physical COG \`mosaic.tif\` from existing local orthophotos.

## Constraints
- Never upload or publish to OpenAerialMap.
- Never modify or delete source \`task_*.tif\` files.
- Preserve local \`data/\`, virtual environment, credentials, and local application outputs during app updates.
- Do not replace final mosaic outputs until a candidate COG validates.
- Do not report a successful build/update when a command fails.
- Do not describe default VRT source priority as alpha-aware blending.
- Windows launcher must invoke PowerShell by its full system path rather than relying on PATH.

## Acceptance criteria
- [ ] Double-clicking \`launch_latest.vbs\` starts \`update_and_run.ps1\` in a visible PowerShell window.
- [ ] Updater checks the latest commit SHA, downloads that commit's archive, checks required files, and skips source download when local SHA matches.
- [ ] Update overlay excludes \`data/\`, \`.venv/\`, \`.git/\`, \`.env\`, \`.streamlit/\`, and GeoTIFF files.
- [ ] Update/dependency failures trigger best-effort rollback of overwritten application files and do not overwrite the local commit marker.
- [ ] Double-clicking \`rebuild_cog.bat\` invokes \`rebuild_cog.ps1\`.
- [ ] COG workflow checks for source inputs and at least 60 GiB free space, builds strict average-resolution VRT candidate, creates COG candidate, and validates it.
- [ ] Existing \`mosaic.vrt\` and \`mosaic.tif\` are only moved after candidate COG validation; backups are kept on successful replacement.
- [ ] Failure before validation leaves final outputs untouched; failed replacement attempts rollback.
- [ ] Both launchers avoid automatic OAM upload.
- [ ] Existing Python tests and launcher-contract tests pass in CI.
- [ ] Windows manual acceptance verifies updater/no-update behavior, local data preservation, COG validation, and rollback on a disposable test dataset.

## Known limitation
The GDAL VRT mosaic uses standard source priority for overlaps; it is not alpha-aware blending. Visual seam review remains required. This spec does not authorize publishing.
