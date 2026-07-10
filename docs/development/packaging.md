# Packaging and deployment

This plugin uses [`qgis-plugin-ci`](https://github.com/opengisch/qgis-plugin-ci/) for
packaging and releasing. Its dependencies live in the `pack` group of `pyproject.toml`,
and its configuration in the `[tool.qgis-plugin-ci]` table.

## Versioning

The plugin version has a single source of truth: the `version=` field of
`stratified_packager/metadata.txt` (which `pyproject.toml` reads dynamically through
`__about__`). You normally **don't edit it by hand**: the `update-metadata` prek hook
(`scripts/update_metadata.py`) rewrites it to the latest entry in `CHANGELOG.md` whenever
the changelog changes.

So bumping the version means adding a release section to `CHANGELOG.md`, which follows
[Keep a Changelog](https://keepachangelog.com/) and [Semantic Versioning](https://semver.org/).
The hook syncs `metadata.txt` on the next commit. To inspect the current values:

```powershell
just version   # print the version
just info      # print the parsed metadata
```

## Package

```powershell
just package latest    # package the latest changelog version
just package 0.1.0     # package a specific version
```

Under the hood this performs a `git archive` based on `CHANGELOG.md`.
Run `just package --help` for the full `qgis-plugin-ci` options.

## Plugin repository manifest (`plugins.xml`)

`just build-xml` generates a `plugins.xml` (the QGIS repository manifest) from
`metadata.txt` via `scripts/build_qgis_repo_xml.py`. The output defaults to
`build/plugins.xml`, and any XML field can be overridden from the command line:

```powershell
just build-xml                                                              # build/plugins.xml
just build-xml dist/plugins.xml --download-url https://example/plugin.zip   # custom path + field
```

Run `just build-xml --help` for every available override.

## Releasing a version

Releases follow a classic git workflow: **1 released version = 1 git tag** (SemVer-compliant).

1. Add the release section to `CHANGELOG.md` (write it manually, or paste GitHub's
   auto-generated release notes). Commit it — the `update-metadata` hook syncs `metadata.txt`.

1. Tag the commit and push the tag:

   ```powershell
   git tag -a 0.1.0 -m "This version rocks!"
   git push origin 0.1.0      # or: git push --tags
   ```

1. The `publishing.yml` workflow runs on the tag and, in order: compiles the translations
   to `.qm`, creates the GitHub Release (notes from `qgis-plugin-ci changelog`), regenerates
   `plugins.xml` with the release download URL, and publishes the package to the
   [officialQGIS plugin repository](https://plugins.qgis.org/) via `qgis-plugin-ci release`
   (using the `OSGEO_USER` / `OSGEO_PASSWORD` repository secrets).

On non-tag pushes to `main`, the same workflow packages a `latest` build and uploads thezip and
`plugins.xml` as artifacts, which the documentation workflow folds into the GitHub Pages site.

### Fixing a botched tag

If a release goes wrong (failed pipeline, missed step), delete and recreate the tag:

```powershell
git tag -d 0.1.0
git push origin :refs/tags/0.1.0
# fix the problem, then re-tag and push again
```
