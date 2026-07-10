# Packaging algorithm

The plugin registers a single Processing algorithm, **`stratified_packager:package`**
(*Package project*). It partitions the open project's layers against a **stratification
layer** and writes **one zipped GeoPackage per stratum** into an output directory.

Features are matched to strata either by **attribute** (following chains of the project's
`QgsRelation`s) or **spatially** (a predicate, including a raw DE-9IM pattern), chosen per
layer. Outputs are zip-only: a `.gpkg` exists on disk only transiently while it is built and
then inside its zip.

## Running it

### From the QGIS GUI

Open *Processing ▸ Toolbox ▸ Stratified Packager ▸ Package project*. The dialog's defaults are
pre-filled from the active project (see [Defaults & precedence](#defaults-precedence)); the
**Layers** field is pre-checked with the eligible layers.

### Headless, with `qgis_process`

`qgis_process` only loads provider plugins that have been enabled **for it** (separately from
the desktop). Enable it once per user profile:

```bash
qgis_process plugins enable stratified_packager
```

Then run the algorithm:

```bash
qgis_process run "stratified_packager:package" \
    --project_path=/path/to/project.qgz \
    --OUTPUT_DIRECTORY=/path/to/out \
    --STRATIFICATION_LAYER=districts
```

`--project_path` is **required** — the algorithm declares
`Qgis.ProcessingAlgorithmFlag.RequiresProject`. The Processing framework re-instantiates the
algorithm *after* the project loads, so project-variable and plugin-setting defaults resolve
correctly without a GUI. `QgsSettings` is per-profile, so `qgis_process` uses the **default
profile** unless you override it.

(parameters)=

## Parameters

Advanced parameters are collapsed in the GUI by default.

| Parameter                                      | Meaning                                                                                                  |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| `LAYERS`                                       | Layers to package; empty = every eligible layer not marked `exclude=true`.                               |
| `STRATIFICATION_LAYER`                         | The partition source — one stratum per feature.                                                          |
| `STRATUM_NAME_EXPRESSION`                      | How each stratum is named (empty = feature id).                                                          |
| `GPKG_PATH_EXPRESSION` / `ZIP_PATH_EXPRESSION` | GeoPackage / zip paths (advanced).                                                                       |
| `OUTPUT_DIRECTORY`                             | Where the zips are published (atomic `.part` rename).                                                    |
| `COMPRESSION_LEVEL`                            | Zip Deflate level 0–9 (0 stores uncompressed).                                                           |
| `OVERWRITE_MODE`                               | `overwrite` \| `error` \| `skip-existing`.                                                               |
| `PROJECT_INCLUSION`                            | `none` \| `gpkg` \| `qgz` — embed a project per stratum.                                                 |
| `STRATA_FROM_SELECTION`                        | Only the stratification layer's *selected* features become strata (fails when nothing is selected).      |
| `USE_TEMP_FOLDER`                              | Build in a temporary folder and publish finished zips (off: build inside the output directory).          |
| `INCLUDE_STYLES` / `INCLUDE_METADATA`          | Embed layer styles / metadata.                                                                           |
| `STYLE_CATEGORIES`                             | Which style categories the QML copies (none checked = all).                                              |
| `KEEP_EMPTY_LAYERS`                            | Keep zero-feature layers as empty tables.                                                                |
| `DEDUPLICATE_SHARED_SOURCES`                   | Write layers sharing a source as one table.                                                              |
| `STAGE_PROVIDERS`                              | Stage every layer of these data providers into a fast local copy first (see the `stage` layer variable). |
| `EXPORT_FULL_PACKAGE` / `FULL_PACKAGE_PATH`    | Also emit the unpartitioned dataset.                                                                     |
| `REPORT`                                       | Run report output: an in-memory table layer when no path is given, else a file.                          |
| `GENERATE_REPORT`                              | Also write a `report.csv` into each published zip.                                                       |
| `EXTRA_DIR`                                    | Extra files copied into every zip root.                                                                  |
| `WARM_START_DIR` / `WARM_START_MODE`           | The warm cache: `off` \| `use` \| `update` (below).                                                      |
| `WRITE_CHECKSUMS`                              | Write a `.sha256` sidecar next to each zip.                                                              |
| `DRY_RUN`                                      | Validate and report without writing packages.                                                            |

The expression contexts for the naming and path expressions expose `@stratum_name`,
`@stratum_name_sanitized`, `@gpkg_path` and `@gpkg_name`.

(per-layer-variables)=

## Per-layer variables

Each layer carries QGIS **layer variables** that tune its participation. Edit them under
*Layer Properties ▸ Variables*, on the plugin's per-layer page, or in the all-layers
**Configure layers for packaging** dialog (plugin menu).

| Variable                                        | Type       | Default | Meaning                                                                                                                        |
| ----------------------------------------------- | ---------- | ------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `stratified_packager_exclude`                   | bool       | `false` | Skip this layer when `LAYERS` is empty.                                                                                        |
| `stratified_packager_matching_method`           | enum       | `auto`  | `auto` \| `attribute` \| `spatial` \| `whole_export`.                                                                          |
| `stratified_packager_spatial_predicate`         | list       | `auto`  | Comma-separated named predicates and/or 9-char DE-9IM patterns, combined with OR (invalid patterns are rejected at run-start). |
| `stratified_packager_relation_path`             | JSON list  | unset   | Pin an ambiguous attribute chain.                                                                                              |
| `stratified_packager_excluded_fields`           | JSON list  | `[]`    | Fields dropped from the export.                                                                                                |
| `stratified_packager_stage`                     | bool       | `auto`  | Force (`true`) or forbid (`false`) staging this layer into a fast local copy; `auto` follows `STAGE_PROVIDERS`.                |
| `stratified_packager_warm_marked`               | bool       | `false` | Layer belongs to the warm cache.                                                                                               |
| `stratified_packager_layer_name`                | expression | unset   | Custom display name inside each embedded per-stratum project (may use `@stratum_name`).                                        |
| `stratified_packager_materialize_virtual_layer` | bool       | `false` | Write a virtual layer's features into the GeoPackage instead of keeping the layer live in the embedded project.                |

With `matching_method = auto`: if a relation path to the stratification layer exists the layer
matches by **attribute**; otherwise, if both the layer and the stratification layer have
geometry, it matches **spatially**; otherwise the run aborts naming the layer and the remedies.
`auto` never resolves to `whole_export` — whole export is always an explicit choice.

For spatial matching, `spatial_predicate` accepts several predicates at once — a comma-separated
list of named predicates (`intersects`, `contains`, `within`, `overlaps`, `crosses`, `touches`)
and/or raw DE-9IM patterns — that combine additively (a feature matches if **any** of them holds).
With `spatial_predicate = auto`, a polygon stratum paired with a line layer (or the reverse)
defaults to "interiors intersect, or the line runs along the polygon boundary", a point on either
side to `intersects`, and otherwise to "interiors intersect".

(defaults-precedence)=

## Defaults & precedence

Every omitted parameter resolves through a four-tier chain:

> **explicit input → project variable (`stratified_packager_<param>`) → plugin setting →
> builtin default**

Project- and layer-scope values are editable from three places, each showing the inherited
effective value as a placeholder:

- the plugin **Options** page (plugin-wide settings, with a note when a project shadows one);
- the **Project Properties** page (project-scoped defaults);
- the per-layer page and the **Configure layers for packaging** dialog (layer variables).

In a GUI session the dialog defaults refresh automatically when you load a project or edit the
relevant variables. The same chain is re-applied at run start, so headless runs and stale
instances resolve identically.

## Warm cache

When a warm-cache directory is set, `WARM_START_MODE=use` begins each stratum GeoPackage from
a cached copy and appends only the layers that are *not* warm-marked; `WARM_START_MODE=update`
first writes every stratum's cache file and only then builds the deliverables, seeded from
that fresh cache — an interrupted run still leaves a complete, reusable cache. If a cached
file no longer matches its warm-marked tables, that stratum falls back to a cold build
(reported as `cold-fallback`).

## Output layout

Each published zip mirrors this structure (optional members depend on the parameters):

```text
<output_directory>/
├── <zip_path>.zip
│   ├── <gpkg_path>.gpkg        # the stratum GeoPackage: one table per layer,
│   │                           #   plus layer_styles / gpkg_metadata when embedded
│   ├── <gpkg_basename>.qgz     # embedded project  (PROJECT_INCLUSION = qgz)
│   ├── data/                   # whole-export & non-vector sources, with sidecars
│   │   └── <table>/…
│   ├── resources/              # style assets (SVGs, images) referenced by the QML
│   │   └── …
│   └── report.csv              # per-zip report (GENERATE_REPORT)
├── <zip_path>.zip.sha256       # checksum sidecar (WRITE_CHECKSUMS)
└── report.csv                  # run report, only when REPORT is given a path here
```

With `PROJECT_INCLUSION = gpkg` the per-stratum project is stored *inside* the GeoPackage (via
`QgsProjectStorage`) instead of as a sibling `.qgz`.

## Reports

The algorithm **always** produces a **run-level report** as the `REPORT` output: with no
destination it is loaded as an in-memory table layer; given a path it is written there (CSV,
GeoPackage, …). Independently, `GENERATE_REPORT` (on by default) adds a **per-zip `report.csv`**
to each published zip. Both are UTF-8 without BOM and are data, not translated. Rows record each
layer's per-stratum status (written, empty, skipped, `cold-fallback`, …), unmatched features
(`<unmatched>`), and — under `DRY_RUN` — what *would* be written.
