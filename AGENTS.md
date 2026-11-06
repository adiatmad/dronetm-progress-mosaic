# Agent instructions

Inspect the README, current code, tests, release/update scripts, and repository state before editing.

## Product and safety constraints

- This is a Windows-first, local-first geospatial desktop tool. Keep imagery and task data on the user's computer unless the user explicitly initiates a sharing/upload workflow.
- Preserve the transactional updater and rollback guarantees. Stage, validate, and smoke-test immutable releases before activation; never replace the active install or output before validation succeeds.
- Preserve original orthophotos and existing outputs. Never overwrite source imagery. Any COG replacement or migration must retain rollback/recovery behavior.
- Validate raster CRS, dimensions, bands, data types, georeferencing, and file integrity from actual GDAL/tool output. Never invent CRS metadata or assume incompatible rasters can be merged safely.
- Keep credentials out of source, logs, command history, and generated artifacts. Treat DroneTM tokens as secrets.
- Keep the distinction between CI checks, native GUI smoke tests, real DroneTM API behavior, and real-project imagery acceptance explicit.

## Required engineering workflow

1. Inspect current branch, working tree, relevant code, tests, updater state, and documented Windows workflow before editing.
2. For non-trivial changes, write or update the existing specification with user outcome, scope, non-goals, constraints, failure modes, and testable acceptance criteria.
3. Work in small vertical red-green-refactor slices. Add regression coverage at the correct seam before changing transactional, raster, or updater behavior.
4. For failures, build a deterministic reproduction, minimise it, rank falsifiable hypotheses, and test one at a time. Exercise rollback paths with failure injection where appropriate.
5. Prefer the smallest coherent diff. Do not add dependencies, abstractions, or new update mechanisms without a concrete requirement.
6. Review separately for spec compliance, data safety, updater atomicity, rollback integrity, and unintended network/upload behavior.
7. Run relevant automated tests and Windows-specific checks where available. Inspect the final diff and report exact commands/results. Do not claim GUI or live DroneTM acceptance from CI alone.

## Quality gates

- Apply the full Anti-Slop core in `antislop.md`.
- This repository has a native desktop GUI and a legacy Streamlit UI. Use UI/UX Pro Max when installed for interface changes, but preserve the Windows-first workflow and existing product language. Verify keyboard/focus, responsive layout where applicable, and real interaction states.
- Model updater/release work as a dependency graph. Do not activate a release until all prerequisite checks pass; parallelise only independent checks.
- Never weaken tests, bypass rollback, delete user data, or make upload/publication automatic without explicit authorization.
