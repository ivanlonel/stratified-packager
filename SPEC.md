# Stratified Packager — Algorithm Specification

Normative specification for the whole `Stratified Packager` plugin — its `StratifiedPackagerAlgorithm`,
its defaults/GUI system, and the plugin shell (architecture & module layout in §18). Where this
document and code disagree, this document wins until it is amended — **update SPEC.md in the same
change that alters behavior**.

Keywords MUST / MUST NOT / SHOULD / MAY follow RFC-2119 usage.

______________________________________________________________________

## 1. Overview

The plugin registers one Processing algorithm (`stratified_packager:package`) that partitions
the open project's layers against a **stratification layer** and emits **one zipped GeoPackage
per stratum** into an output directory. Matching between features and strata is **attribute
based** (chains of project `QgsRelation`s) or **spatial** (predicates incl. raw DE-9IM),
selectable per layer. The algorithm runs from the QGIS GUI and from `qgis_process`
(`--project_path` required; the algorithm declares `Qgis.ProcessingAlgorithmFlag.RequiresProject`).

Outputs are **zip-only**: a `.gpkg` exists on disk only transiently while being built and
inside its zip. The design target is **tens of strata (≤ ~100)** per run; per-stratum provider
re-queries are acceptable, single-scan fan-out writing is not required.

Identity facts: `name()` = `"package"`, provider id = plugin slug, display name
`tr("Package project")` (wording MAY be refined).

### 1.1 Supported versions

- **Primary target: QGIS 4.0+** (Qt6 / PyQt6). Code is written **strictly as-if 4.0** — no
  `qgis.core`/`qgis.gui` version shims, no behavioral fallbacks, no deliberate bias toward
  older APIs when picking among equivalents.
- **Support floor**: the lowest QGIS version whose PyQGIS API covers what the code uses, computed
  from the code and never engineered down. The floor is **3.38** — set by the algorithm's
  unguarded `QgsField(name, QMetaType.Type)` constructor (the QGIS 3.38 QMetaType migration; QGIS
  3.36 lacks the overload). CI audits down to **3.40** (the first LTR version since 3.38), so `metadata.txt` `qgisMinimumVersion` is **3.40**. The one opportunistic newer
  API — `QgsMapLayer.exportSldStyleV3` (3.44) in `algorithm._sld_text` — is called inside a
  `try:`/`except AttributeError:` that falls back to `exportSldStyleV2` (3.30), so it does not raise
  the floor.
- **`qgis.PyQt` exception**: wherever the PyQt6 and PyQt5 idioms differ (import locations such
  as `QAction`, removed/renamed members), code MUST guard with `try:` (PyQt6 idiom) /
  `except ImportError:` (PyQt5 fallback), keeping the fallback branch import-trivial (no logic).
  PyQt6 scoped-enum style is used everywhere unguarded — it is valid on the PyQt5 5.15 builds every
  supported QGIS ships. In practice `qgis.PyQt` already bridges every divergence this plugin touches
  (e.g. `QAction` imports from `qgis.PyQt.QtWidgets` work on both bindings), so no guard is currently
  needed anywhere.
- **Python ≥ 3.12 regardless of QGIS version**: the host QGIS's interpreter must be 3.12+. This
  excludes stock OSGeo4W/Windows builds older than ~3.36 (they bundle older Pythons) while
  admitting e.g. Linux/conda builds of older QGIS — documented in user docs and the algorithm
  help.
- **CI exercises both Qt bindings.** The QA matrix (`.github/workflows/qa.yml`) runs the suite
  on PyQt5 (QGIS 3.40/3.44, Linux + Windows) and PyQt6 (QGIS 4.0+), so the
  `except ImportError:` fallback branches of the `qgis.PyQt` exception above are covered on every
  push — there is no untested-fallback limitation. Tests assert behaviour through `qgis.PyQt` so
  the same test passes under either binding (see `docs/development/testing.md`).

## 2. Definitions

- **Stratification layer** — vector layer (geometry optional) whose features define strata.
- **Stratum** — exactly **one feature** of the stratification layer (no grouping by value).
- **Stratum name** — value of `STRATUM_NAME_EXPRESSION` for that feature; feature id when the
  expression is empty. Strict: see §6.
- **Packaged layers** — layers selected via `LAYERS` (default: all eligible) minus per-layer
  opt-outs; their content lands in the outputs.
- **Traversal-only layer** — a layer not packaged but used as an intermediate hop in a relation
  chain. Any project layer qualifies; no opt-in needed.
- **Whole-export layer** — packaged layer whose `matching_method` resolves to `whole_export`:
  exported complete (never partitioned) into every stratum package. Remains a node of the
  relation graph (§7.1), so it MAY serve as a traversal hop for other layers' chains.
- **Dedup group** — packaged vector layers sharing one normalized data source; written once per
  gpkg as a union table (§12).
- **Staging** — Phase-A copy of a worker-unreadable source into a temp gpkg (§8.2).
- **Warm cache** — directory of per-stratum gpkgs holding only `warm_marked` layers (§11).
- **Full package** — pseudo-stratum `<full>` containing all features of every packaged layer.

## 3. Algorithm parameters

Naming rules (uniform, stated once):

- Project variable for input `X` → `stratified_packager_<x_lower>` (e.g.
  `stratified_packager_compression_level`). **Every** non-`ParameterMultipleLayers` input has one.
- Plugin setting for input `X` → typed `Setting` descriptor `<x_lower>` on
  `StratifiedPackagerSettings` — only for inputs whose builtin default is project-independent
  (column *Setting*).
- Resolution precedence: **explicit input > project variable > plugin setting > builtin
  default** (§5).

| Id                           | Processing type                             | Req. | Builtin default                                                | Setting |
| ---------------------------- | ------------------------------------------- | ---- | -------------------------------------------------------------- | ------- |
| `LAYERS`                     | `ParameterMultipleLayers` (TypeMapLayer)    | no   | empty ⇒ all eligible layers (GUI prefill: §5)                  | —       |
| `STRATIFICATION_LAYER`       | `ParameterVectorLayer` (incl. geometryless) | no¹  | —                                                              | —       |
| `STRATUM_NAME_EXPRESSION`    | `ParameterExpression` (parent: strat layer) | no   | empty ⇒ feature id                                             | —       |
| `STRATA_FROM_SELECTION`      | `ParameterBoolean`                          | no   | `False` (selected strat. features only become strata, §6)      | —       |
| `GPKG_PATH_EXPRESSION`       | `ParameterExpression`                       | no   | empty ⇒ `@stratum_name_sanitized`                              | ✓       |
| `ZIP_PATH_EXPRESSION`        | `ParameterExpression`                       | no   | empty ⇒ `@gpkg_name`                                           | ✓       |
| `OUTPUT_DIRECTORY`           | `ParameterFolderDestination`                | yes  | —                                                              | —       |
| `COMPRESSION_LEVEL`          | `ParameterNumber` int 0–9                   | no   | `6` (0 ⇒ `ZIP_STORED`)                                         | ✓       |
| `OVERWRITE_MODE`             | `ParameterEnum`                             | no   | `overwrite` \| `error` \| `skip-existing`; default `overwrite` | ✓       |
| `PROJECT_INCLUSION`          | `ParameterEnum`                             | no   | `none` \| `gpkg` (embed) \| `qgz` (in zip); default `none`     | ✓       |
| `USE_TEMP_FOLDER`            | `ParameterBoolean`                          | no   | `True`                                                         | ✓       |
| `INCLUDE_STYLES`             | `ParameterBoolean`                          | no   | `True`                                                         | ✓       |
| `STYLE_CATEGORIES`           | `ParameterEnum` (multiple, static strings)³ | no   | every category (empty ⇒ all, §8.1)                             | ✓       |
| `INCLUDE_METADATA`           | `ParameterBoolean`                          | no   | `True`                                                         | ✓       |
| `KEEP_EMPTY_LAYERS`          | `ParameterBoolean`                          | no   | `True`                                                         | ✓       |
| `DEDUPLICATE_SHARED_SOURCES` | `ParameterBoolean`                          | no   | `True`                                                         | ✓       |
| `STAGE_PROVIDERS`            | `ParameterEnum` (multiple, static strings)⁴ | no   | empty (no provider staged implicitly, §8.2)                    | ✓       |
| `EXPORT_FULL_PACKAGE`        | `ParameterBoolean`                          | no   | `False`                                                        | ✓       |
| `FULL_PACKAGE_PATH`          | `ParameterString` (path)                    | no   | empty ⇒ `<sanitized project basename>_full`                    | —       |
| `GENERATE_REPORT`            | `ParameterBoolean`                          | no   | `True` (gates only the per-zip report.csv, §9.2)               | ✓       |
| `REPORT`                     | `ParameterFeatureSink` (table)              | no   | memory layer loaded in the GUI; a path writes a file (§9.1)    | —       |
| `EXTRA_DIR`                  | `ParameterFile` (Folder)                    | no   | —                                                              | —       |
| `WARM_START_DIR`             | `ParameterFile` (Folder)²                   | no   | —                                                              | —       |
| `WARM_START_MODE`            | `ParameterEnum`                             | no   | `off` \| `use` \| `update` (§11); default `off`                | ✓       |
| `WRITE_CHECKSUMS`            | `ParameterBoolean`                          | no   | `False`                                                        | ✓       |
| `DRY_RUN`                    | `ParameterBoolean`                          | no   | `False`                                                        | —       |

¹ Blank is valid only when `EXPORT_FULL_PACKAGE=True` (then only the full package is built).
Blank + `EXPORT_FULL_PACKAGE=False` → validation error.
² The directory MAY not exist yet on `WARM_START_MODE=update` runs; it is created. Required
(validation error if unset) whenever `WARM_START_MODE` is not `off`.
³ Options are the single-bit `QgsMapLayer.StyleCategory` tokens, in QGIS bit order, as offered
by the layer-tree *Styles ▸ Copy Style* menu (the `All*` combinations are excluded). The
parameter is `optional`, so an empty (nothing-checked) selection is accepted and means **all
categories** — the *select-none = select-all* rule; `INCLUDE_STYLES=False` is the real off
switch. Gated by `INCLUDE_STYLES`: when styles are excluded the selection is irrelevant.
⁴ Options are the provider registry's keys (`QgsProviderRegistry.providerList()`), sorted. Every
layer of a selected provider whose `stage` variable is unset/`auto` is staged (§8.2) — the
opt-in "this source is slow, never re-read it once per stratum" switch. An empty selection
stages no provider implicitly. Unknown keys in a stored variable/setting fail validation
(strict, like `STYLE_CATEGORIES` tokens).

The former `MAX_WORKERS` input was **removed**: measurement (94-zip field runs) showed the
background pool never holds more than one active zip — packaging is a single DEFLATE stream that
finishes within the next bundle's build time — so the pool is a fixed two threads (§8.4): one
effectively for packaging, one overlapping the §11 warm prefetch with Phase A.

Relative paths (`FULL_PACKAGE_PATH`, `EXTRA_DIR`, `WARM_START_DIR`) resolve
against `OUTPUT_DIRECTORY`; absolute paths are honored as-is.

Enum values are persisted in settings/variables as the canonical string tokens (not indices,
and not the translated labels the §19 defaults combos display), so stored config survives enum
reordering and locale changes. `STYLE_CATEGORIES` and `STAGE_PROVIDERS` (the
multi-valued inputs) persist as comma-separated token lists; blanks are dropped. An empty
`STYLE_CATEGORIES` resolves to all categories; an empty `STAGE_PROVIDERS` to no provider.

### Declared outputs

| Id                 | Type                | Content                                                                          |
| ------------------ | ------------------- | -------------------------------------------------------------------------------- |
| `OUTPUT_DIRECTORY` | `OutputFolder`      | the resolved output directory                                                    |
| `REPORT`           | `OutputVectorLayer` | run report table; memory layer if no path given, else a file (also on `DRY_RUN`) |
| `ZIP_PATHS`        | `OutputString`      | JSON array of published zip paths                                                |
| `STRATA_COUNT`     | `OutputNumber`      | number of strata resolved                                                        |
| `ZIP_COUNT`        | `OutputNumber`      | number of zips published                                                         |
| `FAILED_STRATA`    | `OutputString`      | JSON array of failed stratum names (empty on success)                            |

`StratifiedPackagerAlgorithmInputDict` / `OutputDict` TypedDicts MUST mirror these contracts.

## 4. Layer-scoped variables

Stored as QGIS **layer variables** (`QgsExpressionContextUtils` layer scope — visible under
*Layer Properties ▸ Variables*, persisted in the project, readable headless). List values are
JSON-encoded strings. Accessed through the toolbelt `LayerVariables` proxy.

| Variable (`stratified_packager_…`) | Type                                                                      | Default | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ---------------------------------- | ------------------------------------------------------------------------- | ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `exclude`                          | bool                                                                      | `false` | skip this layer when `LAYERS` is empty (= "all"); drops it from the `LAYERS` GUI prefill (§5); strict — an uncoercible value aborts at run start (§6), lenient only in the prefill                                                                                                                                                                                                                                                                                                                          |
| `matching_method`                  | `auto` \| `attribute` \| `spatial` \| `whole_export`                      | `auto`  | see resolution below                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `spatial_predicate`                | `auto` \| comma-separated list of named predicates and/or DE-9IM patterns | `auto`  | named ∈ {intersects, contains, within, overlaps, crosses, touches}; DE-9IM = 9 chars of `[TF012*]` (T/F case-insensitive); tokens combine with OR; validated                                                                                                                                                                                                                                                                                                                                                |
| `relation_path`                    | JSON list of relation ids                                                 | unset   | pins the chain when paths are ambiguous                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `excluded_fields`                  | JSON list of field names                                                  | `[]`    | dropped from the exported table                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `stage`                            | bool, or unset = `auto`                                                   | `auto`  | force a per-layer staging copy (§8.2): `true`/`false` override the heuristic; unset/`auto` stages iff `matching_method = whole_export` **or the layer's data provider is in the resolved `STAGE_PROVIDERS` set** (§3). A staged layer is copied once into a local GeoPackage holding only the features some stratum uses, and every stratum reads its slice from there — pure read-amortization for slow sources, never a correctness requirement                                                           |
| `warm_marked`                      | bool                                                                      | `false` | layer belongs to the warm cache (§11); strict — an uncoercible value aborts at run start (§6); marking any member of a dedup group warms the whole group (§12: one shared table — announced with an info message)                                                                                                                                                                                                                                                                                           |
| `layer_name`                       | expression                                                                | unset   | display name of this layer in the embedded per-stratum project (§13); evaluated per stratum with the full project + layer context plus `@stratum_name`/`@stratum_name_sanitized` (feature-less); empty = original name; no effect when `PROJECT_INCLUSION = none`; strict — parse error aborts at run start, eval error/NULL fails that stratum                                                                                                                                                             |
| `materialize_virtual_layer`        | bool                                                                      | `false` | `virtual` provider layers only: `true` materializes the layer into its own gpkg table (packaged like any vector); `false`/unset keeps it **live** in the embedded project — re-pointed at this stratum's gpkg tables (§13) — when every source it queries is already packaged, else falls back to materializing it with an info message; a materialized layer querying a non-local source additionally warns (§8.2); ignored for non-virtual layers; strict — an uncoercible value aborts at run start (§6) |

**`matching_method = auto` resolution** (per packaged, partitioned vector layer): if at least
one relation path to the stratification layer exists → `attribute`; else if both the layer and
the stratification layer have geometries → `spatial`; else **run-start validation error**
naming the layer and the remedies (add a relation, set `matching_method = whole_export`,
exclude the layer, or give the stratification layer geometry). `auto` never resolves to
`whole_export` — whole export is always an explicit choice. A `whole_export` layer is exported
complete into every package and stays in the relation graph (§7.1), so it MAY still serve as a
traversal hop for other layers' chains.

**`spatial_predicate`** is a comma-separated list of tokens (named predicate or DE-9IM pattern)
combined additively with **OR**; the T/F of a DE-9IM pattern is case-insensitive and normalized to
uppercase before use. **`auto`** is a single exclusive token (mixing it with others is a run-start
error) that expands by geometry type, with the layer feature as geometry *a* and the stratum as
*b*: a **point** on either side → `intersects`; a **polygon** stratum × **line** layer →
`T********` OR `*1*******` (interiors intersect, OR the line interior runs along the polygon
boundary, dimension 1); a **line** stratum × **polygon** layer → `T********` OR `***1*****` (the
polygon boundary runs along the line interior); any other **line** pairing → `intersects`;
otherwise (e.g. polygon×polygon) → `T********` (interiors intersect).

Non-vector packaged layers ignore `matching_method`/`spatial_predicate`/`excluded_fields`/
`warm_marked`; their handling is fixed by type (§13–§14): local file-based raster/mesh/point
cloud are implicitly whole-export (copied under `data/`), remote and annotation layers ride
only in the embedded project, plugin layers are excluded with a warning.

## 5. Defaults system & precedence

Resolution chain per input: **input > project variable > plugin setting > builtin**.

- **GUI pre-fill (dynamic defaults)**: `StratifiedPackagerProvider` connects the three
  `QgsProject.instance()` signals that can change a resolved default — `readProject`, `cleared`,
  `customVariablesChanged` — to
  `self.refreshAlgorithms()`, coalesced through a single-shot 0 ms timer
  (`customVariablesChanged` fires mid-load, before `readProject`). The hookups are made **only in
  GUI sessions** (wired from `initGui`, which `qgis_process` never calls): connecting them
  headless segfaults qgis_process. `initAlgorithm()` computes every
  `defaultValue` through the chain at refresh time, so the Processing dialog always shows the
  resolved value (booleans included — a checkbox cannot express "unset", which is why
  runtime-only resolution is insufficient).
- **`LAYERS` carries no `defaultValue`** — deliberately, and it MUST stay that way. The standard
  `ParameterMultipleLayers` widget does not round-trip layer identity: its wrapper resolves
  whatever `defaultValue` it is given to layers and stores each one's **data source** string
  (`QgsProcessingMultipleLayerWidgetWrapper::setWidgetValue`), and `LAYERS` then arrives as one
  source string per layer. Because `QgsProcessingUtils::mapLayerFromString` matches id, then name,
  then source, every string of a shared source resolves to the same first-matching layer — so an
  id-list prefill silently collapses each §12 shared-source group onto one member, repeated,
  dropping the siblings from the package and staging/writing the survivor once per repeat. Left
  unset, the widget never runs that rewrite: an untouched widget sends nothing, and an opened
  picker stores `layer->id()` per row, so even a partial selection of a shared-source group
  resolves exactly. The runtime fallback below is therefore the single authoritative resolution
  for GUI and headless alike: an omitted or empty `LAYERS` resolves to all non-`exclude=true`
  layers at run start. An `exclude` value that cannot be coerced to bool aborts the run (the
  strict regime of §6). Which layers `exclude` removes stays visible on the §19 Options / Project
  Properties / Layer Properties pages and the all-layers table.
  `LAYERS` values that *are* source strings (a saved model, a script, `qgis_process --LAYERS=<source>`) cannot be disambiguated after the fact; the algorithm reports the collapsed
  entries and keeps one per layer rather than failing or guessing.
- **Runtime fallback**: `processAlgorithm` (via `_resolve_inputs`) re-resolves omitted / `None`
  parameters through the same chain, covering headless runs and stale instances. The resolver is
  a single shared helper (`params.InputReader` over `params.resolve_default`) — no per-call drift.
- **qgis_process**: the Processing framework re-instantiates the algorithm
  (`createInstance` → `initAlgorithm`) after `--project_path` is read and before execution,
  so `initAlgorithm`-computed defaults are fresh headless with no signal hookups (which MUST
  NOT be connected there — they segfault). The runtime fallback above stays as the
  safety net, and the help text still documents that omitted parameters resolve through
  project variables / settings.
- `QgsSettings` is per-profile: `qgis_process` uses the default profile unless overridden —
  document in user docs.

## 6. Strata resolution

1. Snapshot taken **once at run start** (algorithm thread): strat-layer features honoring its
   `subsetString`, and — when `STRATA_FROM_SELECTION=True` — only the layer's selected features
   ("run for just these strata"). `STRATA_FROM_SELECTION=True` with an empty selection is a
   run-start error (fail-fast — never a silent full run); the default `False` takes all features
   (honoring the subset string).
1. `STRATUM_NAME_EXPRESSION` evaluates per feature with the full project + strat-layer
   expression context. **Strict regime**:
   - NULL or evaluation error for any feature → `QgsProcessingException` naming the feature.
   - Duplicate raw names → abort, listing collisions.
   - Post-sanitization collisions, compared **case-insensitively** (Windows) → abort, listing
     the colliding pairs.
1. **Filename sanitizer** (`sanitize_filename`, pure-stdlib, in `toolbelt/utils.py`): strips path
   separators and illegal filename chars, collapses whitespace, trims trailing dots/spaces,
   rejects/prefixes Windows reserved names (`CON`, `NUL`, `COM1`…), preserves Unicode letters.
   Property-based tests (hypothesis) required.
1. Naming expression contexts: `GPKG_PATH_EXPRESSION` additionally sees `@stratum_name` and
   `@stratum_name_sanitized`; `ZIP_PATH_EXPRESSION` sees those plus `@gpkg_path` (the gpkg's
   zip-relative path, no extension) and `@gpkg_name` (its basename, no extension). Defaults
   chain: name → feature id; gpkg path → `@stratum_name_sanitized`; zip → `@gpkg_name` — so the
   default zip lands at the `OUTPUT_DIRECTORY` root: a gpkg subpath is an inside-the-zip layout
   choice and never leaks into the output-directory layout unless `ZIP_PATH_EXPRESSION` opts in
   (e.g. via `@gpkg_path`).
1. Path constraints: the gpkg path is relative to its zip's root and MAY contain
   subdirectories, but MUST stay inside the zip (no absolute paths, no `..` escape) and every
   component MUST be a valid filename under the sanitizer's rules (illegal characters, reserved
   device names, trailing dots/spaces) — expression results are validated, never silently
   sanitized; `.gpkg` is appended to the result. The zip path MAY contain subdirectories but
   MUST resolve inside `OUTPUT_DIRECTORY` (no absolute paths, no `..` escape). Violations →
   validation error.
1. **Zip bundling**: several strata MAY map to one zip path (deliberate feature) — bundling
   identity is the **exact** evaluated zip path; two *distinct* zip paths that collide only
   case-insensitively are a validation error (on Windows they would silently overwrite each
   other; spelled-out same paths bundle, case variants abort). Inside one
   zip, gpkg **relative paths** MUST be unique, compared **case-insensitively** (Windows rule);
   identical basenames in different subdirectories are allowed → validation error only on a
   full-path collision. A bundled zip is created
   only after all member gpkgs finished (members failing under best-effort are omitted, noted
   in the report and the zip is still produced with the successful members).
1. Empty strat layer (post-filter) → zero strata: warning; valid run only if
   `EXPORT_FULL_PACKAGE=True`, else error.

## 7. Matching engine

### 7.1 Attribute matching (relation chains)

- Build an undirected multigraph from `QgsProject.relationManager()`: nodes = layer ids, edges
  = relations with their ordered field pairs (composite keys supported) and direction.
  Polymorphic relations are ignored (documented). Cycles MUST NOT cause non-termination.
  Whole-export and traversal-only layers are ordinary nodes — a packaged `whole_export` layer
  MAY appear as an intermediate hop in another layer's chain.
- Path choice per layer: the **unique shortest path** is used automatically; ties →
  **run-start validation error** listing candidate paths and instructing to set
  `relation_path` (ordered relation ids). An invalid pin (id unknown / not a connected chain)
  → validation error.
- Key propagation per stratum: start from the stratum feature's key tuple; per hop, query the
  next layer with an `IN` filter on the linking fields (composite keys → chunked
  `OR`-of-`AND` groups), **honoring that layer's `subsetString`** (selections on intermediates
  are ignored), collecting the far-side key tuples; the final hop yields the target layer's
  WHERE condition. `NULL` keys never match. Hop queries and the §7.2 candidate scans check
  `feedback.isCanceled()` per feature, so cancellation interrupts a large layer mid-scan. Many-to-many fan-out unions naturally; a feature
  MAY belong to multiple strata (it is then written into each one's package).
- `IN` lists are chunked (constant, e.g. 1 000 values/clause, ORed); implementations MAY batch
  hop queries across strata, but the observable result per stratum MUST equal the per-stratum
  definition above.
- A field used by a relation hop may be in `excluded_fields`: exclusion affects only the
  exported schema, never the matching (matching reads the source, not the output).
- Resolving a chain is a **pure function** of the chain and the stratum's starting key tuple: the
  run never reads a project layer for anything but matching and never mutates one (§8.1), so the
  same pair always yields the same condition. Implementations therefore MAY memoize it per run —
  bounded, so memory cannot grow with the stratum count — and the memo MUST NOT change any
  observable result. This collapses two repeats: every packaged layer sharing a chain re-derives
  the identical key set per stratum, and the §8.2 staging pass derives what Phase B derives again.
- **Intermediate** hop layers (every hop but the last, whose far-side keys *are* the condition)
  are read straight from the project, once per `IN` chunk per member per stratum — the one read
  path per-layer staging does not cover, since staging only replaces a *packaged* layer's read
  source. When such a layer's provider is in the resolved `STAGE_PROVIDERS` set (§8.2), it is
  copied once into a local gpkg holding only the fields the chains query, those fields are
  indexed, and the hops read the copy. The copy holds **every** feature: a chain propagates keys
  through the whole intermediate, so a matched-union slice would silently drop rows. A layer that
  is both packaged and an intermediate is therefore staged once per role. Hop staging is an
  optimization — a failure warns and falls back to reading the project layer.

### 7.2 Spatial matching

- Per (layer, stratum): transform the **stratum geometry** into the layer's CRS using the
  project transform context (one transform per pair — never per feature). Log every transform
  with source→target authids. Whether a transform is needed is decided by the
  `QgsCoordinateTransform` itself (`isShortCircuited()` — equivalent or invalid CRSs skip the
  transform), never by string-matching authids. Transform failure fails that pair (best-effort
  containment).
- Candidate filter: `QgsFeatureRequest().setFilterRect(stratum_bbox_in_layer_crs)` — pushed to
  the provider's spatial index. Exact test: a **prepared `QgsGeometryEngine`** built once per
  (layer, stratum) over the stratum geometry (`createGeometryEngine(...).prepareGeometry()`); each
  r-tree candidate is then tested against the OR of the resolved predicates and the matches form
  the fid set. Preparing the (often complex, admin-boundary) stratum polygon turns each test from
  `O(vertices)` into ~`O(log vertices)` — decisive on large layers, and the reason the exact test
  runs as a prepared-engine candidate loop rather than an unprepared C++ filter expression. Named
  predicates map to engine methods, flipping the directional pair (`contains`→`within`,
  `within`→`contains`) because the engine is prepared on the stratum, not the feature; a DE-9IM
  pattern is transposed (the engine computes `IM(stratum, feature)`). GEOS has **no prepared fast
  path for `relate`**, so DE-9IM candidates resolve through prepared primitives first: a prepared
  `contains` **fast-accept** when containment implies the pattern (under `S contains C` the
  transposed matrix is guaranteed `II` non-empty, `IE=F`, `BE=F` — true for the `auto`
  `T********`), then a prepared `intersects` **fast-reject** when the pattern requires
  intersection; only the remaining boundary shell pays the full `relatePattern`. The per-candidate
  test is compiled once per (layer, stratum) — method binding, pattern transposition and the
  implication flags are never re-derived per feature. The stratum geometry is never inlined as
  WKT; only geometry (no attributes) is fetched for candidates.
- The matching **fid set** is computed against the layer's **read source** — the throwaway
  `clone()` it is written from, or its staging copy (§8.2) — so the fids always align with what is
  written. Because `QgsVectorFileWriter` reads through the QGIS provider (there is no separate OGR
  read), the old QGIS-fid ↔ OGR-FID equivalence concern does not arise; a layer read from a staged
  copy simply has its fids recomputed against that copy. The fids select features on the read layer
  (`selectByIds`), written with `onlySelectedFeatures`. Computed lazily, one (layer, stratum) at a
  time, so fid-set memory stays bounded.

## 8. Execution architecture

Three phases. GeoPackage writing runs entirely on the algorithm thread through
`QgsVectorFileWriter` (only that thread may touch QGIS objects); the sole work that leaves it is
qgis-free zip assembly and publishing, on a stdlib `ThreadPoolExecutor` whose jobs
(`processing/workers.py`) **import no `qgis` module — ever**. There is **no `QgsTask`**: its
completion machinery needs a spinning main-thread event loop that neither `processAlgorithm`'s own
worker thread nor `qgis_process` provides.

### 8.1 Phase A — analysis & read sources (algorithm thread, QGIS API)

1. Run-start validation (§15 order).
1. Strata resolution (§6).
1. Per-layer matching-method resolution (§4/§7). The per-stratum membership itself is **not**
   materialized here — it is computed lazily during Phase B against the read source.
1. Per-layer **read source** (§8.2): a throwaway `clone()` of the user's layer (its subset string
   rides along; the user's layer is never read for data nor mutated), or — when the layer is
   staged — a layer over a per-layer staging gpkg holding the union of every stratum's matches.
1. Per-layer payload serialization: QML style strings (`exportNamedStyle` with the resolved
   **`STYLE_CATEGORIES`** — default all, §3, gated by `INCLUDE_STYLES`; resource paths rewritten
   per §14), QGIS layer-metadata XML, kept field lists after exclusions, table names.
1. **Template gpkg**: all **non-warm-marked whole-export vector layers** written once with
   `QgsVectorFileWriter` (data only — per-stratum styles are written after the seed copy, so each
   stratum's `resources/` prefix matches its gpkg depth). Each covered stratum is seeded by a plain
   file copy of the template, then only its partitioned layers are appended. The template also
   becomes the covered layers' **read source** (their staged form, §8.2): a warm-seeded stratum
   (§11) cannot take the template seed, so it writes these layers per stratum — from the local
   template copy, never the original source again.

### 8.2 Staging

Staging is **no longer a correctness requirement**. `QgsVectorFileWriter` reads a layer through its
QGIS provider, so memory providers, joins, virtual/expression fields and unsaved edits are written
directly, and per-stratum matching is computed against the very layer written — the QGIS-fid ↔
OGR-FID equivalence problem that once forced staging is gone (§7.2). Staging is now a pure
**read-amortization** optimization: a source read many times (every whole-export layer; any layer
of a `STAGE_PROVIDERS` provider; any layer the user marks) is copied once into a local gpkg
holding only the features some stratum uses, so each stratum reads its slice from that fast local
file instead of re-fetching from a slow source.

The decision is the layer's tri-state `stage` variable (§4): `true`/`false` force it, unset/`auto`
stages iff `matching_method = whole_export` **or the layer's data provider is in the resolved
`STAGE_PROVIDERS` set** (§3 — measured on the field project: a staged 104k-row attribute select
runs ~100× faster than the same select pushed to PostGIS once per stratum). Whole-export layers
are "staged" via the shared template gpkg (§8.1). For **partitioned** layers, staging is resolved
after dedup grouping (§12) and applied **once per group**: a dedup group stages through its
primary when *any* member's `stage` resolves true (an ungrouped layer stages by itself), so
shared-source layers never build one staging copy per member. On a `WARM_START_MODE=use` run whose
§11 pre-scan found **every** build's warm cache usable, a group whose **every** member is
warm-marked is **not** staged: warm-seeded builds never read it, matching for warm-marked layers
is skipped (§11), and the template excludes them — the staged copy would be written and read by
nothing (a mixed warm/non-warm group still stages; its non-warm members read per stratum). The staging gpkg is built by `stage_union` over **every member's
match plan** — the union of every stratum's matches (or **all** features when
`EXPORT_FULL_PACKAGE` is on, since the `<full>` stratum reads the whole staged copy and would
otherwise drop every feature matching no stratum), retaining each member's matching-key fields
even when `excluded_fields` drops them from output (so matching survives, §7.1) and dropping
geometry-typed attribute columns GeoPackage cannot store. For attribute-matched members an
**attribute index** is created per distinct key-field set, so the N per-stratum key filters are
index lookups rather than full table scans; the spatial filter path already rides the r-tree the
GPKG writer creates by default. A layer read from a staged copy has its per-stratum spatial fids
recomputed against that copy (FID renumbering is irrelevant). Dry runs (`DRY_RUN`, §3) stop
Phase A at analysis: staging copies, the §8.1.5 template and payload/asset placement are
build-side I/O no dry-run output reads, so none of it is performed. Relation-chain intermediates
are staged by the separate, narrower rule in §7.1, before the per-layer staging pass so it benefits
from them.

**Virtual layers over remote sources.** A materialized `virtual` layer (§4) is packaged like any
vector, so its SQLite query is re-executed for every stratum — once to select that stratum's
features and again while the writer reads them. When one of its sources is a database or service
provider this is pathological rather than merely slow: SQLite cannot push a correlated subquery
down, so it pulls the source through QGIS row by row, and the concurrent scans can exhaust the
provider's connection pool (QGIS allows 4 per source) and wedge the run on a connection that is
never granted — observed on a field project, where the same effect froze the QGIS GUI outright.
The plugin therefore **warns** when it materializes a virtual layer whose sources are not local,
naming them and the remedy: push the join into the source (a subset filter, a view, or a
materialized view) and package that layer instead, turning the whole thing into one set-based
query. The warning never changes the routing — staging cannot rescue this shape either, since the
staging pass itself must execute the query once per stratum to compute the union.

**`QgsVectorFileWriter` over `gdal.VectorTranslate`** (despite OGR's per-feature throughput edge):
staging through a single *universal* gpkg re-read per chunk — not writer speed — is what would
dominate runtime and disk. Reading through the provider removes that staging entirely;
provider-pushed selection moves far less data; the whole-export template is written once and
file-copied N times rather than written N times; and writing is sequential — one
`QgsVectorFileWriter` at a time — so the multi-writer contention a fan-out design would hit
never arises (§16).

### 8.3 Phase B — per-stratum assembly (algorithm thread)

Bundles run in order, the strata within a bundle in sequence; one stratum's gpkg is fully built
before the next (no concurrent writers per SQLite file). Per-stratum pipeline
(`processing/building.py`):

1. Seed file: a copy of the warm gpkg (§11) if warm; else a copy of the template (if any); else
   fresh.
1. Append each layer's slice via `QgsVectorFileWriter.writeAsVectorFormatV3` into the stratum gpkg
   (`CreateOrOverwriteLayer` once the file exists). The per-stratum filter is applied on the read
   source, never the user's layer: `whole_export` writes it whole; attribute matching selects by
   the C++-evaluated key expression (the provider compiles `IN` to native SQL where it can);
   spatial matching selects the matched fids — both via `selectByExpression` / `selectByIds`, then
   `onlySelectedFeatures`. An empty selection writes an empty table. A dedup primary writes the
   union of every member's match with the union of their kept fields (§12).
1. Layer order within the gpkg: warm-marked first (cold builds), then template/whole-export, then
   the remaining partitioned layers. A layer already in the seed is not rewritten: warm-marked on
   a warm seed (the cache already carries its per-stratum styles; an empty seeded table follows
   `KEEP_EMPTY_LAYERS`), **non-warm-marked** whole-export on a template seed (warm-marked
   whole-export layers never ride the template, so they are genuinely written) — the latter's
   per-stratum styles are still written so the `resources/` prefix matches.
1. `KEEP_EMPTY_LAYERS=True` ⇒ zero-feature layers keep their (empty) table + style; `False` ⇒ the
   table is dropped, CSV row `status=empty-skipped`.
1. Styles & metadata: raw-SQL inserts (sqlite3) of the Phase-A payloads into `layer_styles` and
   `gpkg_metadata`/`gpkg_metadata_reference` (`styleQML` always — scoped to the
   resolved `STYLE_CATEGORIES`; `styleSLD` best-effort, exported **in full**, not category-scoped:
   the SLD export API has no category filter and SLD represents only symbology + labeling, so the
   selection is honored by the authoritative `styleQML`). One style row per dedup-group member (the
   primary member's is the default, §12).
1. `data/` sidecar payloads (§13) are placed once per bundle in the zip root (§10), not per stratum.

`feedback.isCanceled()` is checked at the top of every loop and passed into the writer so a long
write aborts mid-stream. A stratum failure is **contained** (best-effort, §17) and returned as a
result; the run aborts only at the end if any stratum or zip failed.

### 8.4 Phase C — finalization & background packaging

1. As each bundle's strata finish, the embedded project per member (§13) is built on the algorithm
   thread (cheap, serial), written into the gpkg (project-storage URL §13) or as
   `<gpkg_basename>.qgz` beside it.
1. The finished bundle is handed to a background `ThreadPoolExecutor` (`processing/workers.py`,
   qgis-free `zipfile`/`shutil`): assemble per §10 (the build root is a plain tree walk), publish
   via `.part` + atomic rename, optional checksum. The algorithm thread builds the next bundle's
   GeoPackages while this one compresses. The pool is run-scoped (created before Phase A) and
   **fixed at two threads**: packaging never queues more than one active zip (a zip is a single
   DEFLATE stream that finishes within the next bundle's build time — measured, §3 note), and
   the second thread overlaps the §11 warm-cache prefetch with Phase A. Cancellation reaches
   in-flight jobs via a `threading.Event`.
1. Progress: Phase A ≈ 0–25 % (analysis ≈ 0–5, staging ≈ 5–20, template ≈ 20–25), Phases B+C
   25–95 % weighted by per-(stratum, layer) writes (including the §11 warm pass's on update
   runs) plus per-bundle zips, report + outputs 95–100 %. The bar always reads **overall**
   progress: each writer's internal 0–100 sweep is scaled into that write's slice of its
   band — a `QgsProcessingMultiStepFeedback` stepping inside a band-mapping proxy feedback
   (`setStepWeights` would do both at once but is QGIS 4.0-only, §1.1). `setProgressText`
   names the step the bar is advancing through — the layer being prepared, staged or
   templated, each stratum's per-layer writes, and the embedded-project builds — in step
   with the matching log line.

## 9. Reporting

### 9.1 Run-level report (`REPORT` output)

Always produced — independent of `GENERATE_REPORT` (which gates only §9.2) — and on
`DRY_RUN` too. Emitted through the `REPORT` feature sink: with no destination it is a
**memory table layer** the GUI loads into the project; given a path it is written as that
format (CSV, GeoPackage, …). A text destination (e.g. CSV) is written **UTF-8 without a
BOM** — the sink's file encoding is pinned, not left to the Processing framework's
locale-derived default (the OS codepage, e.g. cp1252) — matching the per-zip report's data
contract (§9.2, §20). A geometryless table whose columns are:

```text
stratum, layer, feature_count, status, detail
```

- One row per (stratum × packaged layer); `status ∈ {ok, warm, cold-fallback, empty-kept, empty-skipped, failed, skipped-existing, dry-run}`; `detail` carries the error text / note. Warm-marked
  layers report `warm` on both `WARM_START_MODE=use` **and** `WARM_START_MODE=update` runs (the
  deliverable pass seeds from the just-written cache, §11).
- `<unmatched>` pseudo-stratum rows: per partitioned layer, the count of features matching no
  stratum (also `pushWarning` per affected layer); warm-marked layers are excluded on
  `WARM_START_MODE=use` runs (§11 — their matched fids are unknowable from a seed).
- `<full>` pseudo-stratum rows when `EXPORT_FULL_PACKAGE=True`.
- The final outputs map (§3) is returned in every completion mode.

### 9.2 Per-zip report (`report.csv` at each zip root)

When `GENERATE_REPORT=True` (the only report this flag gates), every published zip
additionally carries **one combined `report.csv` at its root** (constant name, not
configurable; the `EXTRA_DIR` conflict scan covers it, §10). Never written on `DRY_RUN` (no zips exist then); the `<full>` package's zip
gets one too. CSV is data — UTF-8, no BOM, header row, untranslated (§20). Columns:

```text
stratum, layer_name, gpkg_table, path_in_zip, layer_type, geometry_type, feature_count,
field_count, excluded_fields, matching_method, match_detail, source_crs, status, detail
```

- One row per (member stratum × included layer) — in bundled zips the `stratum` column
  distinguishes members.
- `gpkg_table` — table name inside the gpkg (dedup groups: one row per member layer, all
  pointing at the shared table); empty for layers without a gpkg table.
- `path_in_zip` — `<gpkg_path>.gpkg` for vector tables; the `data/<table name>/…` source path
  for raster/mesh/point-cloud payloads (§14); empty for layers riding only in the embedded
  project (remote, annotation).
- `layer_type ∈ {vector, raster, mesh, point-cloud}`; `geometry_type` filled for vector layers
  only.
- `feature_count` — features exported into this stratum's table (empty for non-vector);
  `field_count` — exported fields after exclusions; `excluded_fields` — semicolon-joined names.
- `matching_method` — as resolved (`attribute` | `spatial` | `whole_export`); `match_detail`
  — the relation-path ids or the spatial predicate used; `source_crs` — CRS authid.
- `status` / `detail` share the run-level vocabulary of §9.1.

## 10. Zip & publish

Layout per zip:

```text
<zip path>.zip
├─ <gpkg_path>.gpkg               (one per bundled stratum; MAY sit in subdirectories)
├─ <gpkg_path>.qgz                (PROJECT_INCLUSION = qgz; beside its gpkg, same basename)
├─ report.csv                     (per-zip report, §9.2 — only when GENERATE_REPORT=True)
├─ data/<layer table name>/…      (whole-export raster/mesh/point-cloud source + sidecars)
├─ resources/…                    (style assets; project-home-relative tree)
│   └─ _ext/<hash8>_<name>        (assets from outside the project home)
└─ <EXTRA_DIR contents>           (zip root, recursive)
```

- Compression: Deflate with `COMPRESSION_LEVEL`; level 0 ⇒ `ZIP_STORED`. Zip64 enabled.
- Name conflicts between `EXTRA_DIR` contents and `*.gpkg` / `*.qgz` / `report.csv` / `data/` /
  `resources/` → validation error (`report.csv` reserved only when `GENERATE_REPORT=True`).
- **SQLite sidecars never ship**: before a bundle's zip job is submitted, each member gpkg is
  WAL-checkpointed (`wal_checkpoint(TRUNCATE)`, best-effort `journal_mode=DELETE`) so the main
  file is complete on its own — the embedded-project build's reads may have switched it to WAL —
  and `*-wal` / `*-shm` / `*-journal` files under the zip root are excluded from the archive (an
  incomplete checkpoint is surfaced as a warning, never shipped silently as a stale main file).
- `USE_TEMP_FOLDER=True`: everything is built under a run-scoped temp dir (created with
  `tempfile.mkdtemp` under the Processing temp folder); each finished zip is copied to
  `<name>.zip.part` in the output dir and atomically renamed (**per zip, as completed** —
  consumers only ever see complete files), and its build copy is deleted once published.
  `False`: build under a hidden `.stratified_build_*` dir inside the output directory (zips
  still assembled as `.part` then renamed); leftover `.stratified_build_*` siblings older
  than 24 h — crash residue; the age guard protects a possibly-live concurrent run — are
  swept at run start.
- End-of-run cleanup (`finally`, best-effort per §17): the workdir-backed read layers
  (staging copies, the whole-export template) are released first — while they are alive GDAL
  holds their files open and Windows refuses deletion — then the build dir is removed with
  bounded retries. Surviving residue (e.g. a handle a failed run's traceback still pins) is
  a warning when the workdir sits inside the output directory, a debug note under the
  Processing temp folder (QGIS removes that folder at exit).
- `OVERWRITE_MODE`: `overwrite` replaces; `error` aborts at run-start validation listing the
  existing targets; `skip-existing` skips those strata (CSV `skipped-existing`).
- `WRITE_CHECKSUMS=True`: `<name>.zip.sha256` written next to each published zip.
- Stale `*.zip.part` files for this run's targets are removed at run start.

## 11. Warm start

- Warm files live in `WARM_START_DIR`, keyed by **sanitized stratum name** (stable across runs
  even when `GPKG_PATH_EXPRESSION` changes); `<full>` is a valid key — **the full package
  participates in warm start** (its cache *file* is named `__full__.gpkg`, since `<`/`>` are
  not legal filename characters; the key stays `<full>` everywhere else). On use, the warm
  file is copied and renamed to the current gpkg name.
- **Cold run** (`WARM_START_MODE=off`): build from scratch; warm-marked layers are written first.
- **Update run** (`WARM_START_MODE=update`): two passes. The **warm pass** first writes *every*
  stratum's cache (including strata whose deliverable zip `OVERWRITE_MODE=skip-existing`
  filtered out — the pass exists to refresh the cache, not the deliverables) — a fresh gpkg holding exactly the warm-marked layers (empty warm tables are
  always kept, independent of `KEEP_EMPTY_LAYERS`, so the cache stays complete), assembled in
  the workdir and published into the warm dir (WAL-checkpointed first, so the copy cannot miss
  un-checkpointed frames; `.part` + atomic rename) — before any deliverable is built, so an
  interrupted run still leaves a complete, reusable cache. The **deliverable pass** then runs
  as a warm run seeded from the fresh cache (warm-marked layers report `warm`); a stratum whose
  cache write failed builds cold instead — never from a possibly-stale pre-existing cache file —
  with CSV `status=cold-fallback` on its warm-marked layers, and the run fails at the end
  listing the unwritten caches (the deliverables still ship, §17).
- **Warm run** (`WARM_START_MODE=use`): start file = copy of the warm gpkg; only non-marked
  layers (+ styles/metadata/project) are appended. A seeded layer's per-stratum matched fids are
  unknowable, so warm-marked layers are excluded from the §9.1 `<unmatched>` accounting on warm
  runs (update runs stay exact — the warm pass records the fids).
- **Warm pre-scan** (warm runs only): Phase A runs the seed-time completeness check (the
  cold-fallback triggers below) against **every** build's cache file (`<full>` included when it
  is exported) before staging. Every cache usable → dedup groups whose every member is
  warm-marked skip §8.2 staging (nothing would ever read their staged copy). Any rejection →
  one `pushWarning` naming the unusable caches and staging proceeds unchanged, so the coming
  cold fallbacks read local staged copies instead of re-fetching remote sources per stratum. A
  cache deleted *after* the pre-scan still cold-falls-back correctly — the §17 guarantee is
  unchanged; only its speed reverts to the source's.
- **Warm prefetch** (warm runs only): before Phase A starts, the background pool (§8.4) copies
  every stratum's cache file from `WARM_START_DIR` (possibly a remote share) to its final build
  path (`.part` + rename, qgis-free `workers.run_prefetch`), overlapping the transfer with
  layer prep and staging. A build whose prefetch landed seeds **in place** — its `warm_start`
  *is* its build path, validated where it sits, no second copy; a failed or unfinished prefetch
  falls back to the normal seed-time copy from the original cache file, and a *rejected*
  prefetched seed is deleted before the template/fresh path runs. Dry runs skip the prefetch.
- `WARM_START_MODE` not `off` with no `WARM_START_DIR` → validation error; with **zero
  warm-marked layers** → run-start validation error (a warm run with nothing warm is always a
  misconfiguration).
- Missing warm gpkg for a stratum, a warm gpkg lacking an expected warm-marked table, or a warm
  gpkg containing a table **not** in the current warm-marked set (appending onto it would
  silently duplicate its features) → **per-stratum cold fallback** with `pushWarning` and CSV
  `status=cold-fallback`.
- Cache staleness (marked-layer data/schema drift) is the user's responsibility; refresh with
  a `WARM_START_MODE=update` run.

## 12. Deduplicated shared sources

- Group key: **provider key + normalized source URI components** via
  `QgsProviderRegistry.decodeUri` (never raw-string comparison — element order and formatting
  must not matter). `decodeUri` leaves path separators and
  identifier quoting as-is, so the key additionally resolves and case-folds
  path-typed components and strips identifier quotes.
- One table per group per gpkg, named after the **first member without a subset string, in
  layer-tree order** (an unfiltered layer's name better represents the whole union); when every
  member is filtered, the **first member in layer-tree order**. The choice affects the table
  name, the default style (the primary member's), and the representative (`group_primary_id`)
  member — all members share the normalized source, so the exported data is identical either way.
- Per-stratum membership = **union of every member's match set** (regardless of each member's
  matching method/predicate/chain; a whole-export member ⇒ full table everywhere).
- Exported fields = **union of every member's kept fields**, where each member's kept fields
  always include the columns referenced by its own subset string — so re-applying the per-layer
  subset strings on the embedded project's layers restores each member's exact view.
- Staging composes with grouping (§8.2): the group stages **once**, through its primary, when any
  member's `stage` resolves true — the staged copy holds the union of every member's matches, so
  members never split into separate tables over staging.
- The embedded project maps every member layer to the shared table.

## 13. Embedded project (`PROJECT_INCLUSION` ≠ none)

Built fresh per stratum on the algorithm thread (never `QgsProject.instance()`); contents:

- Included layers re-pointed at the stratum gpkg tables (dedup-aware), `data/` files (relative
  paths), remote layers with their original sources (offline caveat documented), annotation
  layers carried over.
- **Live virtual layers** (`materialize_virtual_layer=false` with every queried source packaged,
  §4) are carried into the project with their query, uid and geometry preserved and each source
  re-pointed at this stratum's gpkg table; style and attribute-form config ride along (the layer
  is cloned and only its data source swapped). A virtual layer is dropped (with a warning) for any
  stratum missing a referenced table (e.g. `KEEP_EMPTY_LAYERS=False`). Source references resolve by
  layer id, or by exact provider+source match for embedded sources. When a source is not packaged,
  the layer is materialized into its own table instead (§4) and behaves like any packaged vector.
- **Layer display names** honor the `stratified_packager_layer_name` expression (§4) when set,
  evaluated per stratum (`@stratum_name`/`@stratum_name_sanitized`); empty inherits the original
  name. Only the project's display name changes — gpkg table names are unaffected.
- **Layer tree structure** (groups, order, visibility) restricted to included layers; **styles**
  for the resolved `STYLE_CATEGORIES` (default all, §3; the same rewritten QML payloads the gpkg
  `layer_styles` rows use); **relations** remapped among
  included layers (relations touching excluded layers are dropped); **project CRS, transform
  context, title**. No print layouts, map themes, macros, actions.
- Per-layer subset strings re-applied (§12). Layers whose stratum table is absent
  (`KEEP_EMPTY_LAYERS=False`) are omitted from that stratum's project.
- Paths stored relative (`Qgis.FilePathType.Relative` set explicitly; gpkg storage already
  defaults to relative datasources). `gpkg` mode writes into the GeoPackage's project storage
  (URL `geopackage:<absolute gpkg path>?projectName=<stratum name>`, via `QgsProject.write`) with
  the stratum name as project name; `qgz` mode writes `<gpkg_basename>.qgz` beside the gpkg inside
  the zip.
- Broken/invalid layers are never included (bad-layer policy).
- The member gpkg is **held in WAL journal mode for the whole build** (best-effort,
  `gpkg.wal_session`: switch to WAL, materialize the `-wal` sidecar with a no-op
  `gpkg_contents` touch, and keep that connection open until the build returns), so QGIS's
  pooled read-only connections detect the sidecar at open time and retry without *nolock*,
  instead of breaking mid-statement when a later write materializes it. A fire-and-forget
  flip is not enough — closing the flipping connection auto-checkpoints and deletes the
  sidecar, and GDAL's nolock decision keys on the sidecar's existence; the §10 pre-zip
  checkpoint folds and reverts the file afterwards.
- The re-pointed layers open with `loadDefaultStyle=False` (their style is applied explicitly
  from the exported QML — the same payload the gpkg `layer_styles` rows carry, so nothing is
  lost) and `skipCrsValidation=True` (the CRS comes from the gpkg), skipping redundant
  per-layer reads in the per-stratum build.

## 14. Auxiliary file bundling

- **Layer payloads** (`data/<table name>/…`): whole-export local file-based raster, mesh and
  point-cloud layers — source file plus sidecars (`QgsFileUtils.sidecarFilesForPath`, world
  files, `.aux.xml`, overviews); directory-based sources (e.g. ESRI grid) copied whole.
  Caveat + `pushWarning` when a copied container file (e.g. a `.gpkg`) also backs other
  project layers (the copy drags the whole container).
- **Style assets** (`resources/…`): files referenced by included layers' symbology/labeling
  (SVG markers, raster fills, images, fonts where file-based), discovered via a symbol-layer /
  style-entity walk. Files under the project home keep their project-relative subtree; foreign
  files land in `resources/_ext/<hash8>_<name>` (hash of the absolute source path). Paths
  inside QGIS-builtin resource locations (`QgsApplication.svgPaths()` etc.) are **not**
  bundled — they resolve on any QGIS install. QML payloads (gpkg `layer_styles` and embedded
  project alike) are rewritten to the bundled relative paths.

## 15. Validation & edge cases

**Static validation** (`checkParameterValues` — cheap, no data access): parameter presence and
coherence (¹/² of §3), expression parse checks, enum/range checks, warm-flag exclusivity,
path-shape rules (§6.5).

**Run-start validation** (top of `processAlgorithm`, before any writes — failures raise
`QgsProcessingException`): strat-layer rules incl. geometry-needed check; strata resolution
(§6 strict rules); per-layer matching resolution incl. ambiguity/pin errors and invalid
`spatial_predicate` tokens (unknown name, malformed DE-9IM, or `auto` combined with others);
dedup grouping;
`OVERWRITE_MODE=error` existence scan; `EXTRA_DIR` conflict scan (incl. `report.csv`, §10);
evaluated gpkg-path shape checks (§6.5); bundle-internal gpkg path uniqueness (§6.6); warm
requirements incl. the empty-warm-set error (§11).

Edge-case catalog (behavior MUST be tested):

- Empty strat layer / empty selection → §6.7.
- Layer with neither relation path nor geometry → named error (§4).
- Geometryless strat layer + any layer resolved `spatial` → named error.
- Invalid `spatial_predicate` token (unknown name, malformed DE-9IM, or `auto` combined with
  others) on a spatially-resolved layer → named run-start error (§4); multiple tokens OR-combine.
- Huge key/fid lists → chunked `IN` (constants documented in code).
- Windows: long paths, reserved device names, case-insensitive collisions (§6), non-ASCII
  names preserved.
- Zips > 4 GiB → zip64.
- Cancellation: the algorithm thread checks `feedback.isCanceled()` at every loop top and passes
  the feedback into each `writeAsVectorFormatV3` (a long write aborts mid-stream); background zip
  jobs abort via a `threading.Event`; temp dir removed (best-effort, §10); `.part` files
  removed; already-published zips remain (best-effort semantics); CSV reflects reality.
- Disk-full / permission errors during publish → that stratum fails (best-effort), others
  continue.
- A feature matching multiple strata is written to each (expected, documented).
- Orphan features → `<unmatched>` accounting (§9), never silently invisible.
- `STRATA_FROM_SELECTION=True` + stratification layer without selection → run-start error
  (fail-fast, §6); the default `False` takes all strat-layer features.
- Warm cache missing/incomplete → cold fallback path (§11).
- Duplicate layer names → table-name suffixing `_2`, `_3` in tree order + `pushWarning`;
  tables are named `safe_table_name(slugify(layer_name))` before suffixing — a leading `_`
  is added when the slug would begin with a reserved GeoPackage/SQLite prefix (`gpkg`,
  `sqlite_`), which OGR/SQLite refuse as table names.
- Stratum names sanitizing to `<full>`-like literals cannot collide: sanitizer strips `<`/`>`.
- Gpkg paths: subdirectory components validated as filenames; `..` / absolute → error;
  identical basenames in different subdirs of one bundled zip are valid; full-path collisions
  (case-insensitive) abort (§6.5–6.6).
- Warm gpkg holding an extra (no-longer-marked) table → cold fallback, never a duplicate
  append (§11).
- A `whole_export` layer in the middle of another layer's relation chain → the chain works
  (§7.1).

## 16. Performance requirements

- Push down everywhere available: provider spatial index via `setFilterRect`; C++-evaluated
  filter expressions; OGR `where` clauses into the driver; never per-feature Python in bulk
  paths.
- Bounding-box test always precedes the exact predicate.
- **GeoPackage writing is sequential** on the algorithm thread — one `QgsVectorFileWriter` at a
  time. Parallel writing is deliberately not used: it was measured to regress throughput past ~4
  concurrent writers, and one stratum's write already saturates RAM. Speed comes instead from: no
  universal staging gpkg; provider-pushed per-stratum selection moving only matched features;
  whole-export data written once into the template and file-copied per stratum; and matching
  computed lazily, one (layer, stratum) at a time. The fixed two-thread background pool (§8.4)
  covers zip packaging and the §11 warm prefetch; nothing else is configurable, because the pool
  never queues more than one active zip (§3 note). `gdal.VectorTranslate` has a per-feature
  throughput edge over `writeAsVectorFormatV3`, but the writer is adopted anyway (§8.2): reading
  through the QGIS provider removes the staging blow-up that would otherwise dominate runtime.

## 17. Error handling & cancellation

- **Best-effort policy**: a failing stratum is contained (partials cleaned, CSV `failed`,
  `reportError`); remaining strata run to completion; at the end, any failure raises
  `QgsProcessingException` listing failed strata, zips, and warm-cache writes (§11; run marked
  failed for models/chains) while the outputs map still reports what was published
  (`FAILED_STRATA` lists deliverable failures only).
- **Embedded-project write is degraded delivery, not a stratum failure**: when a stratum's
  data gpkg built but its embedded project (§13) could not be written, the gpkg still ships —
  `qgz` mode without the `.qgz` (a partial is cleaned), `gpkg` mode without project storage —
  a `pushWarning` is emitted, and the member stays successful (absent from `FAILED_STRATA`;
  the run is not marked failed on its account). Only the project *write* is degraded delivery:
  assembling the plan first evaluates the §4 `layer_name` expressions, and an eval error/NULL
  there **fails the stratum** (§4's strict rule; its gpkg is discarded like any failed
  stratum's). The reason `QgsProject.write` returns `False`
  is otherwise discarded, so it is captured (the QGIS message log emitted during the write,
  else filesystem facts about the destination) into the exception/warning detail. Crucially,
  the gpkg is **never** unlinked on this path — the fresh project still holds an OGR handle on
  it, so a Windows `unlink` would raise `PermissionError` and (not being a
  `QgsProcessingException`) escape the run.
- `QgsProcessingException` is the only exception that may escape `processAlgorithm`
  (repo exception-containment rule). Worker exceptions are caught at the worker boundary,
  serialized through the queue, and accounted on the algorithm thread.
- All user-facing messaging during execution flows through `feedback` exclusively
  (repo rule); workers never touch `feedback` directly (queue relay only).

## 18. Architecture & module layout

**Plugin shell & lifecycle.** `classFactory(iface)` (`__init__.py`) calls `QgisLoggerWrapper.setup`
(installing a `QgisContextFilter` that stamps the plugin version and QGIS context onto every
record), then lazily imports and returns `StratifiedPackager` (`main.py`). `StratifiedPackager`
implements the QGIS lifecycle: `initGui` registers the three defaults-editing widget factories
(§19), the menu actions and the provider-signal hookups (§5, GUI-only); `initProcessing`
registers `StratifiedPackagerProvider`; `unload` reverses all of it (unregister factories +
provider, disconnect signals, `deleteLater` the actions, tear down the settings-tree node, detach
the logging handler last). `main.py` imports the `gui` package lazily inside `initGui`, so
`qgis_process` never loads the GUI modules.

**Identity.** `__about__.py` parses `metadata.txt` at import (stdlib-only, no `qgis`, so setuptools
can read `__version__` at build time) and re-exports `__title__`, `__version__`, `__icon_path__`,
etc. `identity.py` derives `PLUGIN_SLUG` (`slugify(__title__)`), which names the `plugins/<slug>`
settings scope and the `stratified_packager_*` variable/object-name prefix, and hosts
`plugin_icon()`, the cached multi-resolution `QIcon` assembled from the `resources/images/png`
bitmaps (every icon consumer uses it — no on-the-fly SVG rasterizing); it imports neither
`settings` nor `processing.params`, so both can depend on it without a cycle.

**Settings.** `settings.py`'s `StratifiedPackagerSettings` subclasses the plugin-agnostic
`PluginSettingsBase` (`toolbelt/settings.py`), scopes itself under `plugins/<slug>`, and declares
the §3 setting-backed inputs as typed `Setting` descriptors.

**Toolbelt.** A plugin-agnostic library (no dependency on this plugin's identity or domain);
purity constraints are listed after the tree.

```text
stratified_packager/
  __init__.py                    # classFactory(iface) entry point: QgisLoggerWrapper.setup, then lazy plugin import
  __about__.py                   # identity source — parses metadata.txt via ConfigParser; stdlib-only (no qgis)
  identity.py                    # PLUGIN_SLUG (settings scope + variable/object-name prefix) + plugin_icon()
  main.py                        # StratifiedPackager: initGui / initProcessing / unload lifecycle
  settings.py                    # grows the typed Setting descriptors of §3
  processing/
    provider.py                  # StratifiedPackagerProvider(QgsProcessingProvider) — registers the package algorithm
    algorithm.py                 # orchestration: validation driver, phase sequencing, run report sink
    params.py                    # parameter declarations, TypedDicts, InputReader (input→var→setting resolver)
    material.py                  # Phase-A→B/C hand-off records + shared helpers (field_indexes/warm_file_name/is_warm_marked)
    strata.py                    # §6: strata resolution, naming, sanitization checks, zip bundling
    matching.py                  # §7: relation graph, chain traversal, spatial fid sets
    dedup.py                     # §12: source-key normalization, group merge, warm-group promotion
    virtual.py                   # §4/§13: virtual-layer materialize-vs-live routing
    staging.py                   # §8.2: per-layer staging decision + staged-uri helper
    building.py                  # §8.3: algorithm-thread gpkg assembly via QgsVectorFileWriter
    workers.py                   # §8.4 background zip publishing + §11 warm prefetch — MUST NOT import qgis (zipfile/shutil/stdlib only)
    project_builder.py           # §13: embedded per-stratum project construction
    bundling.py                  # §14: data/ payload collection + resources/ style-asset walk
    report.py                    # §9: row dataclasses, status tokens, CSV writing — qgis-free
    reporting.py                 # §9: qgis-side row assembly (run + per-zip) and orphan accounting
  gui/
    dlg_layers_table.py          # all-layers table dialog
    wdg_layer_options_page.py    # Layer Properties page factory
    wdg_plugin_options_page.py   # extended Options page (plugin scope + override notes)
    wdg_project_options_page.py  # Project Properties page factory
    widgets.py                   # reusable scope-editor widgets shared by all hosts
  toolbelt/                      # plugin-agnostic library (no dependency on this plugin's identity/domain)
    logging.py                   # QgisLoggerWrapper / QgisHandler — the handler/wrapper facade
    logging_records.py           # Target / filters / MessageBar+BoxConfig / level mapping — the record layer logging.py builds on
    settings.py                  # QGIS settings proxies (SettingsProxy / PluginSettingsBase / …); registers QColor converter
    mapping_proxy.py             # qgis-free foundation: converter registry + MappingProxy + EnvironmentVariables
    relations.py                 # generic QgsRelation graph + pathfinding (plugin-agnostic)
    zipping.py                   # stdlib zip/publish helpers (.part/rename, levels, zip64) — qgis-free
    gpkg.py                      # OGR/sqlite gpkg helpers (table-drop, introspection, layer_styles/metadata SQL) — qgis-free
    sql.py                       # SQL-text helpers for the SQLite/GeoPackage dialect (quote_identifier, safe_table_name) — qgis-free AND osgeo-free
    utils.py                     # pure-stdlib helpers (+ filename-grade sanitizer) — qgis-free
    i18n.py                      # Translatable Protocol — tr classmethod for non-QObject classes
    debugging.py                 # optional env-gated debugpy bootstrap
```

Tests mirror 1:1 (`tests/...`), per repo convention. Each sub-package carries a trivial
`__init__.py` marker (omitted above), and GUI pages load sibling `.ui` skeletons via
`uic.loadUiType` (§19). Toolbelt modules stay plugin-agnostic; `zipping.py`, `gpkg.py`,
`sql.py` and `utils.py`'s sanitizer are `qgis`-free (`sql.py` and `mapping_proxy.py` also
`osgeo`-free), usable in `scripts/`.

## 19. Defaults-editing GUI (hybrid)

- **Plugin scope** — existing Options page extended with the new settings; each field shows a
  small note "⚠️ overridden by project variable (= X)" when the current project shadows it.
- **Project scope** — new Project Properties page via `registerProjectPropertiesWidgetFactory`;
  empty field = inherit (shows the inherited effective value as placeholder); clearing falls
  back to the plugin default.
- **Layer scope** — both: (a) per-layer page via `registerMapLayerConfigWidgetFactory`; (b) a
  dedicated **all-layers table dialog** (plugin menu): rows = project layers, columns =
  include / matching method (incl. `whole_export`) / predicate / excluded fields /
  warm-marked, link
  buttons to the Options and Project Properties pages, and a per-row button opening that
  layer's properties at the plugin's per-layer page (`iface.showLayerProperties(layer, page=…)`).
- Every scope editor is a plain reusable `QWidget` hosted by its container(s); `.ui` files
  loaded via `uic.loadUiType` per repo rule. All factories registered in `initGui` are
  unregistered in `unload` (incl. signal disconnects for §5).

**Implementation.** The repetitive per-field rows are built programmatically from three
shared field tables (`gui/widgets.py`: `default_fields()` = the 17 ✓ settings of §3;
`project_only_fields()` = the two variable-only §3 inputs (below); `layer_fields()` = the 9 §4
variables), so the GUI cannot drift from the parameter/variable
schema. Each `.ui` file therefore carries only the page **skeleton** (header + an empty host
widget / `QTableWidget`, still loaded via `uic.loadUiType`); the editor rows are inserted into
it at construction. The scope editors (`OverrideLineEdit`, `OverrideComboBox`,
`OverrideCheckBox`, `OverrideCheckableCombo`, `OverrideFieldsCombo`, `OverridePredicateCombo`,
`OverrideSpinBox`, `OverrideExpressionEdit`, `OverrideLayerCombo`, composed by `OverrideForm`)
run in two modes. **Project Properties** is
inheritance-aware (`inheriting=True`): an empty value / dedicated "inherit" item means inherit,
shown as an `inherit (= X)` placeholder naming the next-tier effective value. The Project
Properties page additionally prepends the two **project-only** rows — `STRATIFICATION_LAYER`
and `STRATUM_NAME_EXPRESSION`, the §3 inputs with a project variable but no plugin setting
(their values are project-dependent, so they get no global Options row).
`STRATIFICATION_LAYER` edits through an `OverrideLayerCombo` (`QgsMapLayerComboBox` filtered to
`Qgis.LayerFilter.VectorLayer`, geometryless tables included, with a "not set" empty row) and
stores the layer **id** the runtime resolver feeds to `QgsProject.mapLayer` (§5); an id absent
from the current project loads as unset, so applying the page clears the stale value
(fail-fast). `STRATUM_NAME_EXPRESSION` edits through an `OverrideExpressionEdit`
(`QgsExpressionLineEdit`) whose builder receives the currently selected stratification layer
(`layerChanged → setLayer`); empty = unset (⇒ feature id, §3). Both editors' inherited-value
placeholder is a no-op — there is no setting tier beneath them. The **per-layer
page and the all-layers table** are non-inheriting (`inheriting=False`): the §4 layer variables
have no project/plugin tier, only a builtin default, so the unset state is shown plainly — the
2-state booleans (`exclude`, `warm_marked`, `materialize_virtual_layer`) as `OverrideCheckBox`
checkboxes (checked = `true`, unchecked = unset — these all default `false`; the checkbox is
default-aware, so a True-default bool would render inverted: checked = unset, unchecking =
`false`); the tri-state `stage` and the `matching_method`
enum as an `OverrideComboBox` whose plain sentinel item (`auto`, data `None`) is the unset
default, so selecting it clears the variable while `stage`'s explicit `Enabled`/`Disabled`
(`true`/`false`, force-on/force-off) stay expressible; and `layer_name` / `relation_path` /
`spatial_predicate` as plain placeholders ("keep original" / "auto"). Token-enum combos on every
defaults surface show translated labels and store the §3 token (`FieldSpec.labeled_choices`, read
back via `currentData()`), as the multi-enum editors already did; only the Processing run dialog
shows raw tokens (§20). The Options page instead
uses concrete editors (always a real value) plus the override note. Constrained values
avoid free-text editing where the widget stays simple: integer fields (`compression_level`)
use range-bound spin boxes (concrete `QSpinBox` on the Options page;
inheritance-aware `OverrideSpinBox`, a below-range sentinel value = inherit, on the Project
Properties page), and per-layer `excluded_fields` uses a multi-select of the layer's own field
names (`OverrideFieldsCombo`; nothing checked = inherit on the Project Properties page, unset on
the layer pages where it keeps the bare `QgsCheckableComboBox` default text; stored as the JSON
list the matching engine reads). `STYLE_CATEGORIES`
edits through a checkable multi-select (`QgsCheckableComboBox`): concrete on the Options page,
and inheritance-aware (nothing checked = inherit, shown via `setDefaultText`) on the Project
Properties page. The per-layer page covers vector layers
(`supportsLayer`) and the all-layers table disables the matching-only columns
(method/predicate/excluded fields) for non-vector rows. Page deep-links use
`showOptionsDialog(currentPage="wdg_stratified_packager_plugin_options_page")` (the page
widget's `.ui` objectName) and `showProjectPropertiesDialog(currentPage=<plugin title>)`
(`QgsProjectProperties` overwrites the page objectName with the factory title); the per-row
layer button opens `showLayerProperties(layer, page="wdg_stratified_packager_layer_options_page")`
(plugin-registered pages keep their own object names). The all-layers table omits `relation_path`
(the ambiguity pin stays on the per-layer page). No GUI API used is newer than the §1.1 floor.

## 20. i18n & docs

- Every user-facing string — parameter names/descriptions, enum/combobox labels, errors, warnings,
  debug messages (CSV is data, not translated) — goes through `tr()` or
  `QCoreApplication.translate()` per repo rules. Sole exception: the Processing run dialog's enum
  options stay raw §3 tokens — the static-string `QgsProcessingParameterEnum` makes the shown text
  the stored/CLI value, so translating it would break the token contract; the §19 defaults combos
  show translated labels and store tokens.
- Counts that may need singular vs. plural wording use the `%n` placeholder with the count argument;
  every such message MUST carry `numerus="yes"` in the `.ts` (pylupdate may omit it — fixed by
  hand), and the Portuguese/Spanish translations supply both plural forms.
- `shortHelpString()` documents every parameter, the layer variables, the precedence chain,
  warm-start lifecycle and the qgis_process usage (`--project_path`). Under a dark palette it
  prepends a `<style>` block recolouring the help body to the palette text colour (QGIS's help
  widget hardcodes light-theme greys that vanish on dark panels); light themes are left untouched.
- Sphinx docs page covering the same plus the zip layout diagram.

## 21. Test plan

- Fixtures: temp-dir gpkg-backed projects built in-test (no committed binaries): strat layer +
  chains (direct, 2-hop via traversal-only layer, composite keys, ambiguous paths, cycles),
  spatial cases per predicate (incl. boundary-touch vs `T********`), mixed CRS, memory layers,
  subset strings, selections, joins.
- Coverage targets per repo: ≥ 80 % overall, ≥ 90 % on `processing/` core.
- Required scenarios: every §15 edge case; dedup unions (features + fields + styles);
  warm cold/update/warm/fallback flows incl. `<full>`, the update run's caches-before-deliverables
  ordering, drift in both directions and the empty-warm-set error (§11); bundling; overwrite
  modes ×3; dry-run; checksums; cancellation
  mid-run (Event observed); the run report (§9.1) asserted on the produced `REPORT` layer's
  fields and rows (memory destination and a written file); a CSV golden file for the per-zip
  report (§9.2 — incl. a bundled multi-stratum zip, dedup rows and `data/` payload rows); gpkg subpaths
  (component validation, `..`/absolute rejection, case-insensitive bundle collisions, `.qgz`
  beside its gpkg, default zip at the output root); `matching_method=whole_export` incl. a
  whole-export layer as a traversal hop; `LAYERS` prefill refresh on project/layer signals
  (`@pytest.mark.qgis`); zip content assertions via `zipfile`; embedded project re-opened and
  verified (tree/styles/relations/subset strings) under `@pytest.mark.qgis`.
- `workers.py` and the qgis-free toolbelt modules get plain (non-qgis-marked) tests.
- Hypothesis: sanitizers, IN-chunking, zip-path validation.

## 22. Future work (explicitly out of v1)

- Per-stratum raster clipping (gdal.Warp cutline).
- Orphans package (export `<unmatched>` features as an extra archive).
- SQL FOREIGN KEYs via table rebuild and/or GeoPackage Related Tables Extension.
- `TARGET_CRS` output reprojection.
- Group-by-expression strata mode (many stratification layer features per stratum).
