# Stratified Packager

A [QGIS](https://qgis.org) plugin that splits one master project into **one zipped
GeoPackage per zone** — "zones" being the features of any layer you choose.

Say you maintain a state-wide project (parcels, roads, hydrography, imagery…) and every
field team should only receive the data of its own municipality. Stratified Packager takes
your **stratification layer** (the municipalities), works out which features of every other
layer belong to each of them, and publishes `MUNICIPALITY_A.zip`, `MUNICIPALITY_B.zip`, …,
each containing a self-contained GeoPackage — optionally with a ready-to-open QGIS project,
the layer styles, and every file the styles reference.

## How it works

The plugin registers a single Processing algorithm, **`stratified_packager:package`**
(*Package project*). Each feature of the stratification layer becomes one **stratum**. Every
packaged layer is matched to strata either **by attribute** — following chains of the
project's relations from the layer to the stratification layer — or **spatially** — testing
its geometries against each stratum's geometry with one or more predicates (including raw
DE-9IM patterns). Layers that should ship whole into every package can be marked
`whole_export`. The matched slice of every layer is written into that stratum's GeoPackage,
and each GeoPackage is zipped and published atomically into the output directory.

## Quickstart (QGIS Desktop)

1. Install the plugin (see [Installation](#installation)) and open your project.
1. Open *Processing ▸ Toolbox ▸ Stratified Packager ▸ Package project*.
1. Pick the **stratification layer**, a **stratum name expression** (e.g. a name column) and
   the **output directory**. The **Layers** field comes pre-checked with every eligible
   layer.
1. Run. One `.zip` per stratum lands in the output directory, plus a run report listing
   what was written (or skipped) per layer and stratum.

Tip: run once with **Dry run** enabled to validate the configuration and preview the report
without writing any package.

## Parameters

Advanced parameters are collapsed in the GUI by default. Every parameter marked ✓ can also
be given a per-project default (a project variable named
`stratified_packager_<parameter_name_in_lowercase>`) and/or a plugin-wide default (the
plugin's Options page); an omitted parameter resolves through **explicit input → project
variable → plugin setting → builtin default**.

| Parameter                    | What it does                                                                                                        | Default               | Project var | Setting |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------- | --------------------- | :---------: | :-----: |
| `LAYERS`                     | The layers to package. Empty = every eligible layer not marked with the `exclude` layer variable.                   | all eligible layers   |             |         |
| `STRATIFICATION_LAYER`       | The layer whose features define the strata (may be a geometryless table when all matching is by attribute).         | —                     |      ✓      |         |
| `STRATUM_NAME_EXPRESSION`    | Expression naming each stratum.                                                                                     | the feature id        |      ✓      |         |
| `STRATA_FROM_SELECTION`      | Only the stratification layer's *selected* features become strata (fails if nothing is selected).                   | `false`               |      ✓      |         |
| `GPKG_PATH_EXPRESSION`       | Expression for each GeoPackage's path inside its zip.                                                               | the sanitized name    |      ✓      |    ✓    |
| `ZIP_PATH_EXPRESSION`        | Expression for each zip's path inside the output directory (strata may share a zip).                                | the GeoPackage name   |      ✓      |    ✓    |
| `OUTPUT_DIRECTORY`           | Where the zips are published (each copied as `.part`, then atomically renamed).                                     | —                     |      ✓      |         |
| `COMPRESSION_LEVEL`          | Zip Deflate level 0–9 (0 = store uncompressed).                                                                     | `6`                   |      ✓      |    ✓    |
| `OVERWRITE_MODE`             | What to do when a target zip already exists: `overwrite`, `error`, or `skip-existing`.                              | `overwrite`           |      ✓      |    ✓    |
| `PROJECT_INCLUSION`          | Embed a QGIS project per stratum: `none`, `gpkg` (stored inside the GeoPackage) or `qgz` (a sibling file).          | `none`                |      ✓      |    ✓    |
| `USE_TEMP_FOLDER`            | Build in a temporary folder and publish finished zips, instead of building inside the output directory.             | `true`                |      ✓      |    ✓    |
| `INCLUDE_STYLES`             | Embed each layer's style into its GeoPackage (and the embedded project).                                            | `true`                |      ✓      |    ✓    |
| `STYLE_CATEGORIES`           | Which style categories to copy (symbology, labels, forms, …). None checked = all.                                   | all                   |      ✓      |    ✓    |
| `INCLUDE_METADATA`           | Embed each layer's metadata.                                                                                        | `true`                |      ✓      |    ✓    |
| `KEEP_EMPTY_LAYERS`          | Keep layers with no matching features as empty tables (with styles) instead of dropping them.                       | `true`                |      ✓      |    ✓    |
| `DEDUPLICATE_SHARED_SOURCES` | Write layers that share one data source as a single table (their styles all ride along).                            | `true`                |      ✓      |    ✓    |
| `STAGE_PROVIDERS`            | Stage every layer of these data providers (e.g. `postgres`) into a fast local copy before the per-stratum writes.   | none                  |      ✓      |    ✓    |
| `EXPORT_FULL_PACKAGE`        | Additionally emit the whole, unpartitioned dataset as a pseudo-stratum.                                             | `false`               |      ✓      |    ✓    |
| `FULL_PACKAGE_PATH`          | Path of that full package.                                                                                          | `<project name>_full` |      ✓      |         |
| `GENERATE_REPORT`            | Write a `report.csv` into each published zip.                                                                       | `true`                |      ✓      |    ✓    |
| `REPORT`                     | The run-level report output: an in-memory table layer when no path is given, else a file.                           | in-memory layer       |             |         |
| `EXTRA_DIR`                  | A directory whose contents are copied into every zip root (readme files, terms of use, …).                          | —                     |      ✓      |         |
| `WARM_START_DIR`             | The warm-cache directory (see [Warm cache](#warm-cache)).                                                           | —                     |      ✓      |         |
| `WARM_START_MODE`            | `off`, `use` (start each stratum GeoPackage from its cached copy) or `update` (refresh every cache, build from it). | `off`                 |      ✓      |    ✓    |
| `WRITE_CHECKSUMS`            | Write a `.sha256` checksum sidecar next to each published zip.                                                      | `false`               |      ✓      |    ✓    |
| `DRY_RUN`                    | Validate everything and produce the report, but write no packages.                                                  | `false`               |      ✓      |         |

The naming and path expressions can use `@stratum_name`, `@stratum_name_sanitized`,
`@gpkg_path` and `@gpkg_name`.

## Per-layer variables

Each layer can carry QGIS **layer variables** tuning how it is packaged. Edit them under
*Layer Properties ▸ Variables*, on the plugin's per-layer properties page, or — for all
layers at once — in the **Configure layers for packaging** dialog (plugin menu).

| Variable (prefix `stratified_packager_`) | Default | What it does                                                                                                                                             |
| ---------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `exclude`                                | `false` | Skip this layer when `LAYERS` is empty.                                                                                                                  |
| `matching_method`                        | `auto`  | `auto`, `attribute`, `spatial` or `whole_export`. `auto` prefers a relation path, then spatial; it never picks `whole_export` on its own.                |
| `spatial_predicate`                      | `auto`  | Comma-separated named predicates (`intersects`, `contains`, `within`, `overlaps`, `crosses`, `touches`) and/or 9-character DE-9IM patterns, OR-combined. |
| `relation_path`                          | unset   | JSON list of relation ids pinning one attribute chain when several equally short ones exist.                                                             |
| `excluded_fields`                        | `[]`    | JSON list of field names dropped from the exported table.                                                                                                |
| `stage`                                  | `auto`  | Force (`true`) or forbid (`false`) staging this layer's data into a fast local copy before the per-stratum writes; `auto` follows `STAGE_PROVIDERS`.     |
| `warm_marked`                            | `false` | The layer belongs to the warm cache.                                                                                                                     |
| `layer_name`                             | unset   | Expression giving the layer a custom display name inside each embedded per-stratum project (may use `@stratum_name`).                                    |
| `materialize_virtual_layer`              | `false` | Write a virtual layer's features into the GeoPackage instead of keeping the layer live (with its query) in the embedded project.                         |

## Warm cache

Packaging jobs often re-ship large layers that rarely change (imagery indexes, base
cartography). Mark those layers `warm_marked`, give the algorithm a `WARM_START_DIR` and set
`WARM_START_MODE`:

- **`update`** first writes every stratum's cache file (only the warm-marked layers), then
  builds the deliverables seeded from that fresh cache — an interrupted run still leaves a
  complete, reusable cache behind;
- **`use`** begins each stratum GeoPackage from its cached copy and only computes and
  appends the non-warm-marked layers.

A cached file that no longer matches its warm-marked tables falls back to a cold build for
that stratum (reported as `cold-fallback`).

## Desktop vs. `qgis_process`

The algorithm runs identically from the QGIS GUI and headless. Differences to know:

- `qgis_process` keeps its **own** plugin enablement — enable the plugin once per user
  profile: `qgis_process plugins enable stratified_packager`.
- `--project_path` is **required**: the algorithm reads the layers, relations and variables
  of an open project.
- Plugin settings are stored per QGIS *user profile*; headless runs use the **default
  profile** unless you point `qgis_process` at another one.
- Project variables and plugin settings still apply to omitted parameters — the precedence
  chain above is re-resolved at run start, with or without a GUI.

A complete headless run:

```bash
qgis_process plugins enable stratified_packager   # once per profile

qgis_process run "stratified_packager:package" \
    --project_path=/data/state.qgz \
    --STRATIFICATION_LAYER=municipalities \
    --STRATUM_NAME_EXPRESSION='"name"' \
    --OUTPUT_DIRECTORY=/data/packages \
    --PROJECT_INCLUSION=qgz \
    --EXPORT_FULL_PACKAGE=true
```

## Installation

Requires QGIS **3.40 or newer** (Qt 5 and Qt 6 builds are both supported).

- **From the QGIS plugin repository (recommended):** *Plugins ▸ Manage and Install
  Plugins…*, search for *Stratified Packager*, install.
- **From a ZIP:** download a release from the
  [releases page](https://github.com/ivanlonel/stratified-packager/releases) and use
  *Plugins ▸ Manage and Install Plugins… ▸ Install from ZIP*.

## Documentation

The full documentation — algorithm reference, settings, output layout, reports, development
guide and API — lives at
**<https://ivanlonel.github.io/stratified-packager/>**. The complete behavioral
specification is published there as well.

## License

[GPL v2](LICENSE) — the standard license for QGIS plugins.
