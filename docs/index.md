# {{ title }} - Documentation

> **Description:** {{ description }}\
> **Author and contributors:** {{ author }}\
> **Latest version released:** {{ release_version }}\
> **Actual development version:** {{ version }}\
> **QGIS minimum version:** {{ qgis_version_min }}\
> **QGIS maximum version:** {{ qgis_version_max }}\
> **Source code:** {{ repo_url }}\
> **Last documentation update:** {{ date_update }}

______________________________________________________________________

```{toctree}
---
caption: Usage
maxdepth: 1
---
Installation <usage/installation>
usage/algorithm
usage/settings
```

```{toctree}
---
caption: Contribution guide
maxdepth: 1
---
development/contribute
Specification <development/spec>
development/environment
development/documentation
development/translation
development/packaging
development/testing
development/history
```

```{toctree}
---
caption: API Reference
maxdepth: 2
---
api/generated/stratified_packager
```
