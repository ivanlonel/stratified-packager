# CHANGELOG

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

<!--

## Unreleased - YYYY-DD-mm

-->

## Unreleased

- Processing GUI: the progress bar now always reads **overall** run progress — each GeoPackage write's internal 0–100 sweep is scaled into that write's slice of the SPEC §8.4 progress bands (via `QgsProcessingMultiStepFeedback` over a band-mapping proxy) instead of clobbering the bar — and the text above the bar follows the step actually in progress ("Staging layer …", "Writing template layer …", per-stratum layer writes) instead of freezing at the last "Preparing layer" line.

## 0.1.1 - 2026-07-12

- plugins.qgis.org submission: the repository's Bandit scan flagged the identifier-quoted `COUNT(*)` query in `toolbelt/gpkg.py` (B608). The line now also carries a targeted `# nosec B608` — it already had ruff's equivalent `# noqa: S608`, but Bandit does not honor `noqa` comments. No behavior change.

## 0.1.0 - 2026-07-12

First public release.

- `stratified_packager:package` Processing algorithm: partitions the open project's layers against a stratification layer and publishes one zipped GeoPackage per stratum, with atomic `.part` renames and optional `.sha256` sidecars.
- Per-layer matching by attribute (following chains of project relations, composite keys included) or spatially (named predicates and raw DE-9IM patterns, OR-combined), resolved automatically per layer or pinned via layer variables.
- Defaults system with `explicit input > project variable > plugin setting > builtin` precedence, editable from the plugin Options page, the Project Properties page, the per-layer properties page and the all-layers table dialog.
- Embedded per-stratum QGIS projects (stored inside each GeoPackage or as a `.qgz` beside it) with relative sources, styles, metadata and relations.
- Style and metadata copying with style-category selection; `data/` payload bundling for local raster/mesh/point-cloud layers and `resources/` bundling for style assets (SVG markers, textures).
- Warm-start cache modes (`off`/`use`/`update`) with background prefetch, shared-source deduplication, opt-in staging of remote providers, a full-package pseudo-stratum and a dry-run mode.
- Run-level report output (memory layer or file) and a per-zip `report.csv`; headless operation via `qgis_process` (exercised end-to-end in CI).
- English, Spanish and Portuguese translations.
