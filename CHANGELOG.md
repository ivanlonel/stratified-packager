# CHANGELOG

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

<!--

## Unreleased - YYYY-DD-mm

-->

## Unreleased - 2026-07-21

- Processing: **fixed every staging and template step being logged twice.** `setProgressText` already writes its text to the algorithm's log — the Processing dialog appends the progress text to its log panel and `qgis_process` prints it to stdout — so the two steps that additionally pushed the same line as an info message emitted each line twice in the run log. The redundant push is gone; the progress label and the log line itself are unchanged.

## 0.2.0 - 2026-07-20

- Processing: **fixed a multi-part `FULL_PACKAGE_PATH` producing the wrong output layout.** `FULL_PACKAGE_PATH` is the full package's zip path, but the code used only its last component as the zip name (flattened to the `OUTPUT_DIRECTORY` root) and the *whole* path as the in-zip GeoPackage path, never consulting `GPKG_PATH_EXPRESSION` — so `sub/dir/name` wrote `name.zip` at the root containing `sub/dir/name.gpkg`. `FULL_PACKAGE_PATH` is now the (extensionless) zip path in full, and the in-zip GeoPackage path follows `GPKG_PATH_EXPRESSION` like every stratum (empty ⇒ the zip basename). Single-part paths are unchanged.
- Reporting: **fixed the run report (`REPORT` output) being written in the system locale encoding instead of UTF-8.** The per-zip `report.csv` is stdlib-written UTF-8, but the run report rides a Processing *feature sink* whose byte encoding the framework seeds from the OS codepage (cp1252 on a pt-BR Windows), so accented stratum/layer/detail text came out mojibake. The sink is now pinned to UTF-8 (no BOM) for text destinations; GeoPackage and memory-layer destinations are unaffected.
- Processing GUI: **fixed layers sharing a data source being dropped from every run started from QGIS Desktop.** `LAYERS` was pre-filled with layer ids so the dialog opened with the eligible layers pre-checked, but the standard multiple-layers widget does not round-trip identity — its wrapper rewrites the value into one *data source* string per layer, and source-keyed resolution answers every string of a shared source with the same first-matching layer. A project with, say, eight layers over one table therefore packaged that one layer eight times and silently lost the other seven, staging and writing the survivor once per loss. `qgis_process` was never affected: it omits `LAYERS` and resolves by id. `LAYERS` now carries no default, so both paths resolve identically and even a partial selection of a shared-source group is exact; the dialog shows an empty selection, which already means "all eligible layers". A `LAYERS` value that still arrives as source strings (a saved model or script) is reported rather than silently collapsed.
- Matching: relation-chain resolution is now memoized per run (bounded LRU). Every packaged layer sharing a chain used to re-derive the identical key set for each stratum, and the SPEC §8.2 staging pass re-derived what Phase B derived again — on a remote database that was the dominant cost of a run. The memo is an optimization only: results are unchanged, and a test asserts memoized and unmemoized resolutions agree.
- Matching: relation-chain **intermediate** hop layers can now be staged. They were the one read path staging never covered — read straight from the project, once per `IN` chunk, per member, per stratum — because staging only replaces a *packaged* layer's read source. A hop layer whose provider is in `STAGE_PROVIDERS` is copied once into a local GeoPackage holding just the fields the chains query, with those fields indexed. Opt-in, and a staging failure falls back to reading the project layer rather than failing the run.
- Virtual layers: materializing one whose sources are **not local** now warns, naming the sources and the remedy. Such a layer's query is re-executed per stratum, and because SQLite cannot push a correlated subquery down to a database provider it pulls the source through row by row — enough concurrent scans exhaust QGIS's 4-connection pool and wedge the run. Detection only; routing is unchanged.
- SPEC: fixed the §4 `stage` row, which documented `auto` as staging only `whole_export` layers and omitted the `STAGE_PROVIDERS` clause that §8.2 states and the code has always implemented.
- Translations: **fixed the style-category options showing in English in every locale.** The `STYLE_CATEGORIES` table resolved its 18 labels at module import, and that module is loaded from the settings schema while `classFactory` runs — before the plugin installs its translator — so the labels froze to source English while every neighbouring label translated normally. They are now authored with `QT_TRANSLATE_NOOP` and translated on access, as the rest of the plugin already did. The selectable tokens are unchanged.
- Development: `just deploy` now compiles the translation files first. `.qm` files are git-ignored and removed by `just clean`, so a deploy could mirror a plugin whose translator never installs, leaving the entire plugin untranslated.
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
