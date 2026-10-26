# Spec: Transactional one-click updater and validated COG rebuild

## Goal

Provide two independent Windows double-click workflows for DroneTM Progress Mosaic:

1. Update and launch the local native GUI from an exact Git commit without touching the live install until the candidate is verified.
2. Rebuild `mosaic.vrt` and a physical Cloud Optimized GeoTIFF `mosaic.tif` from existing local orthophotos.

## Non-negotiable constraints

- Never upload or publish to OpenAerialMap automatically.
- Never modify or delete source `task_*.tif` files.
- Preserve the root `data/`, credentials, existing local configuration and root virtual environment during updates.
- Never overlay a downloaded update into the live installation.
- Do not replace final mosaic outputs until the candidate COG validates.
- Do not claim Windows or full-project behavior succeeded without the corresponding test evidence.
- Do not describe default VRT source priority as alpha-aware blending.

## Updater design requirements

- Resolve `main` using GitHub's `/commits/main` API and validate a 40-character lowercase commit SHA.
- Download the archive for that exact commit using `archive/<sha>.zip`; never download a moving `main` archive.
- Extract to a temporary directory and sync to a new staging/release directory with `robocopy /MIR`, excluding `data`, `.git`, `.venv`, `.streamlit`, and other local state directories via `/XD`, and local config/GeoTIFF/preview files via `/XF`.
- Check required application files, install dependencies into a staging-local virtual environment, and run a minimal import smoke test before activation.
- Retain each version in a timestamped sibling directory under `.installations/`. On first migration from the legacy root layout, create a timestamped legacy snapshot without moving or overwriting root data or the root environment.
- Use an atomic state-pointer replacement to activate a verified release. A dependency failure must leave the old pointer unchanged; a post-switch failure must atomically restore the old pointer. Never restore by copying old source files over a live installation.
- Keep the no-update path, local GUI launch, and previous releases available.

## COG rebuild requirements

- Require existing `task_*.tif` inputs and the current minimum free-space safety gate.
- Build a timestamped temporary VRT with `gdalbuildvrt`.
- Build a temporary COG using `gdal_translate -of COG -co COMPRESS=DEFLATE -co OVERVIEWS=AUTO` (additional compatible options are allowed).
- Validate the candidate using `validate_cloud_optimized_geotiff.py` when available, otherwise `rio cogeo validate`; GDAL's COG validator is an explicit fallback.
- Only after validation, atomically replace final `mosaic.vrt` and `mosaic.tif` using same-volume file replacement and timestamped backups.
- If either replacement fails, restore previous outputs. If automatic restoration itself fails, preserve backup files and report the exact recovery path.
- Keep source orthophotos untouched and never add OAM upload/publication behavior.

## Acceptance criteria

- [x] Updater pins the download to the SHA returned by `/commits/main` and downloads `archive/<sha>.zip`.
- [x] Updater stages via `robocopy /MIR` with exclusions for local data, config, environment and imagery.
- [x] Dependencies and import smoke test run in staging before activation.
- [x] Releases use timestamped sibling directories and an atomically replaced active state pointer.
- [x] Windows CI injects a dependency-install failure and a post-switch failure, and asserts the old pointer, old install content, and local data remain intact.
- [x] COG build uses temporary VRT/COG candidates and required compression/overview options.
- [x] Candidate COG validation precedes atomic final-file replacement; old outputs are archived and replacement rollback is implemented.
- [x] No automatic OAM upload/publication is added.
- [ ] Latest full CI run passes all Python tests, PowerShell syntax checks, and Windows rollback fault-injection tests.
- [ ] Manual acceptance on the user's Windows installation confirms the updater's first migration/no-update behavior and runs the COG rebuild on a disposable raster set before using the full project.

## Known limitation

The GDAL VRT mosaic uses standard source priority for overlaps; it is not alpha-aware blending. Visual seam review remains required. This spec does not authorize publication.
