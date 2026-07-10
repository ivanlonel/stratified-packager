# Settings & defaults

Every algorithm parameter that is left empty resolves through a four-tier chain (see
[Defaults & precedence](#defaults-precedence)):

> **explicit input → project variable → plugin setting → builtin default**

The plugin ships three editing surfaces for those stored tiers, plus one for the per-layer
variables. All of them show the *inherited* effective value as a placeholder, so an empty
field always means "inherit from the next tier".

## Plugin Options page

*Settings ▸ Options… ▸ Stratified Packager* edits the **plugin settings** — the plugin-wide
base values stored in the active QGIS user profile (`QgsSettings`, under
`plugins/stratified_packager`). Only the parameters with a ✓ in the *Setting* column of the
[parameter table](#parameters) have a setting tier.

When the open project shadows a setting with a project variable, the page marks that field,
so it is always clear which value a run would actually use.

Because settings are per-profile, `qgis_process` reads the **default profile**'s values
unless it is pointed at another profile.

## Project Properties page

*Project ▸ Properties… ▸ Stratified Packager* edits the **project variables**
(`stratified_packager_<parameter_name_in_lowercase>`), stored inside the project file. An
empty field inherits from the plugin setting (or the builtin default) and shows that
inherited value as an `inherit (= …)` placeholder.

Two inputs are *project-only* (they reference project contents, so a plugin-wide default
would make no sense): the **stratification layer** and the **stratum name expression**.

## Per-layer pages

The **layer variables** (`stratified_packager_exclude`, `…_matching_method`, and the rest
of the [per-layer table](#per-layer-variables)) are stored on each layer and
editable from two places:

- *Layer Properties ▸ Stratified Packager* — one layer at a time;
- the **Configure layers for packaging** dialog (plugin menu) — every layer of the project
  in one editable table.

Layer variables have no project or plugin tier: an unset variable simply uses its builtin
default (`auto`, `false`, …), which the editors show as the placeholder.

## Editing values by hand

All three tiers are ordinary QGIS storage, so they can also be edited without the plugin's
pages: project variables under *Project ▸ Properties… ▸ Variables*, layer variables under
*Layer Properties ▸ Variables*, and settings in the profile's configuration. The plugin
validates stored values at run start and aborts loudly on an unusable one (for example, a
boolean variable holding `maybe`) instead of guessing.
