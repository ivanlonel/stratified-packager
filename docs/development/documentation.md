# Documentation

The documentation is built with [Sphinx](https://www.sphinx-doc.org). Custom pages are
written in Markdown via the [MyST parser](https://myst-parser.readthedocs.io/); the API
reference is generated from the in-code docstrings.

## Stack

- **Sphinx** with the [Read the Docs theme](https://sphinx-rtd-theme.readthedocs.io/).
- **MyST** for the Markdown pages under `docs/usage/` and `docs/development/`, with
  extensions such as `colon_fence`, `linkify` and `substitution` enabled in `docs/conf.py`.
- **autodoc** + **autosummary** + [`sphinx-autodoc-typehints`](https://github.com/tox-dev/sphinx-autodoc-typehints)
  render the API reference from docstrings into `docs/api/generated/`.
- [`sphinx-copybutton`](https://sphinx-copybutton.readthedocs.io/) adds copy buttons to code blocks.

Project identity (title, version, author, icon) is read from `stratified_packager/metadata.txt`
through `stratified_packager/__about__.py`, and the changelog is parsed from `CHANGELOG.md`.
The build dependencies live in the `doc` group of `pyproject.toml`.

## Build

```powershell
just build-docs            # HTML (default)
just build-docs latexpdf   # PDF via LaTeX
```

The HTML lands in `docs/_build/html/`; open `docs/_build/html/index.html`. The build is
**strict**: it runs with `-W --keep-going` and `conf.py` enables nitpicky mode, so
warnings — including unresolved cross-references — are collected and then fail the build.
Fix them rather than suppressing them.

## Preview locally

Serve the built HTML and open it in a browser:

```powershell
just serve-docs  [PORT]   # http.server on docs/_build/html (default port 8000)
just browse-docs [PORT]   # open http://localhost:PORT
```

For an iterative workflow, use live reload instead:

```powershell
just autobuild-docs [PORT]   # build + serve + watch + open browser (default port 8000)
```

[`sphinx-autobuild`](https://github.com/sphinx-doc/sphinx-autobuild) builds the docs,
serves them at `http://localhost:PORT`, opens your browser, and rebuilds and reloads the
page whenever a file under `docs/` or `stratified_packager/` changes. Unlike `build-docs`
it runs without `-W`, so in-progress warnings don't block the preview — re-run
`just build-docs` for the strict, CI-equivalent check.

## Adding a page

Create a Markdown file under `docs/` and register it in a `toctree` in `docs/index.md`
(the master document). Then rebuild.

## Cleaning

`just clean` removes the generated output, including `docs/_build` and the autosummary
stubs under `docs/api/generated`.

## Continuous deployment

The `documentation.yml` GitHub Actions workflow builds the docs with the same strict flags
and deploys them to **GitHub Pages** on every push to `main` and on tags. The Pages site
also serves the plugin's `plugins.xml`, so it doubles as the QGIS plugin repository.
