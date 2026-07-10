# Installation

The plugin requires **QGIS 3.40 or newer** (both Qt 5 and Qt 6 builds are supported) and
has no dependencies beyond what QGIS bundles.

## Stable version (recommended)

The plugin is published on the official QGIS plugins repository:
<https://plugins.qgis.org/plugins/stratified_packager/>.

In QGIS, open *Plugins ▸ Manage and Install Plugins…*, search for **Stratified Packager**
and click *Install Plugin*.

## From a ZIP archive

Download a packaged release from the GitHub releases page,
<https://github.com/ivanlonel/stratified-packager/releases>, then use
*Plugins ▸ Manage and Install Plugins… ▸ Install from ZIP*.

## Headless use (`qgis_process`)

`qgis_process` keeps its own plugin enablement, separate from the desktop. After
installing, enable the plugin once per user profile:

```bash
qgis_process plugins enable stratified_packager
```

See [the algorithm page](algorithm.md) for a complete headless run.
