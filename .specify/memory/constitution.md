# DroneTM Progress Mosaic — Engineering Constitution

## I. Local-first data handling
Task metadata, credentials, and imagery remain local by default. Network access is limited to the configured DroneTM API and explicitly requested update/download operations. Never add background uploads or telemetry.

## II. Preserve source imagery
Original orthophotos are immutable inputs. Validate derived rasters before replacing any output, and retain a recoverable prior version until the replacement is proven valid.

## III. Transactional updates
New application releases must be staged, validated, and smoke-tested before activation. Activation and rollback must be atomic where supported. A failed update must leave the previous working version usable.

## IV. Geospatial correctness
CRS, geotransform, dimensions, bands, data types, nodata, and raster validity must be derived from real metadata. Never invent or silently rewrite geospatial metadata to make a merge succeed.

## V. Test failure paths
Updater, pointer, archive, and COG replacement changes require success-path and failure-injection coverage, including rollback and data preservation.

## VI. Honest platform evidence
Distinguish unit tests, Windows CI, packaged executable checks, native GUI interaction, live API behavior, and real-project imagery acceptance. One category does not prove another.

## VII. Small, maintainable changes
Prefer focused changes, explicit state transitions, minimal dependencies, and documented invariants. Avoid speculative abstractions and generic UI.

## Governance
Use existing `specs/` artifacts as the durable source of scope and acceptance criteria. Amend this constitution only when the product-wide safety or release contract changes.
