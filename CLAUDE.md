# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. You are an expert in PyQGIS and QGIS plugin architecture.

## Project

`Stratified Packager` is a QGIS plugin (primary target QGIS 4.0+, supported down to the QGIS 3.40 floor — see SPEC §1.1) that registers a single Processing-framework algorithm: it partitions the open project's layers against a *mold layer* — spatially or by attribute via the project's `QgsRelation`s — and emits one zipped GeoPackage per partition. Runtime is Python 3.12+ under QGIS (PyQGIS, `processing`, Qt6 — Qt5 reached only via the `qgis.PyQt` guards of the *Cross-version compatibility* rule, `mod_spatialite`); CLI entry is `qgis_process`. Dependencies via **uv** (`pyproject.toml` / `uv.lock`); tasks via **justfile** on **PowerShell 7 (`pwsh`)**; pre-commit hooks via **prek**, configured in `.pre-commit-config.yaml`.

## Architecture

- **Entry point**: `classFactory(iface)` in `stratified_packager/__init__.py`. Lazily imports `StratifiedPackager` after calling `QgisLoggerWrapper.setup` with a `QgisContextFilter` that stamps `plugin_version` and QGIS context onto every record.
- **Identity source**: `stratified_packager/__about__.py` parses `stratified_packager/metadata.txt` at import via `ConfigParser`, validates the `[general]` section against `QgisPluginMetadataGeneral`'s required keys, and re-exports `__title__`, `__version__`, `__icon_path__`, `__uri_homepage__`, etc. `pyproject.toml` reads `__version__` from here via `[tool.setuptools].dynamic.version`, so `__about__` MUST stay stdlib-only (no `qgis`) — setuptools imports it at build time. **Edit `metadata.txt` to change either; it must stay valid (parsed at import time).** The QGIS-derived slug `PLUGIN_SLUG` (`slugify(__title__)` → `QgsStringUtils.unaccent`; the `plugins/<slug>` settings scope and the `stratified_packager_*` variable/object-name prefix) therefore lives in `stratified_packager/identity.py`, not `__about__`. `identity.py` also hosts `plugin_icon()`, the cached multi-resolution `QIcon` assembled from the `resources/images/png` bitmaps — every icon consumer uses it, never `QIcon(str(__icon_path__))` (no on-the-fly SVG rasterizing). `identity.py` imports neither `settings` nor `processing.params`, so both can depend on it without a circular import.
- **`main.py`** — `StratifiedPackager`. Implements the QGIS-mandated `initGui` / `initProcessing` / `unload` lifecycle. `unload` reverses `initGui`, unregister providers, disconnect signals, calls `.deleteLater()` on `QAction`s, and tears down the plugin's settings-tree node via `StratifiedPackagerSettings.teardown()`. Inherits `Translatable` (not `QObject`) for `tr`.
- **`settings.py`** — `StratifiedPackagerSettings`, the plugin's concrete settings schema. Subclasses the plugin-agnostic `PluginSettingsBase` from `toolbelt/settings.py`, sets `_PLUGIN_NAME = PLUGIN_SLUG` (imported from `identity.py`), and declares the plugin's typed keys (`debug_mode`, `version_saved`, the SPEC §3 algorithm defaults) as `Setting` descriptors. Binds `__version__` into the settings layer (via `version_saved`) and imports `processing.params` for token-list defaults (e.g. `style_categories`) and for the setting descriptions (single-sourced from `ParamSpec.label` via `_setting_label`); the toolbelt stays generic.
- **`processing/`**
  - `provider.py`: `StratifiedPackagerProvider(QgsProcessingProvider)`. Provider id = `PLUGIN_SLUG`.
  - `algorithm.py`: `StratifiedPackagerAlgorithm(QgsProcessingAlgorithm)` — **behavior is normatively specified in `SPEC.md` (repo root): read it before touching the algorithm, and amend it in the same change that alters behavior.** Orchestrates the SPEC §18 modules: `params` (declarations + `InputReader` input→variable→setting resolution; also hosts the single-source text tables — `PARAM_SPECS` rows carry a `QT_TRANSLATE_NOOP` `label` reused by the dialog, the Options/Project pages and the setting descriptions, and `LAYER_VAR_SPECS` carries each §4 layer variable's default/label/description/flags for the GUI and the algorithm help), `strata`, `matching`, `staging` (per-layer staging decision), `material` (the Phase-A→B/C hand-off records + shared helpers the phase modules depend on), `dedup` (§12 shared-source grouping), `virtual` (§4/§13 virtual-layer routing), `building` (algorithm-thread gpkg assembly via `QgsVectorFileWriter`: clone-and-select per stratum, the whole-export template, per-layer `stage_union`), `workers` (qgis-free zip publishing + warm prefetch), `project_builder` (§13 embedded projects), `bundling` (§14 `data/` payload + `resources/` style-asset collection), `reporting` (qgis-side §9 row assembly) and `report` (qgis-free §9 tokens/rows/CSV + the canonical `STATUS_*` tokens). `StratifiedPackagerAlgorithmInputDict` / `OutputDict` TypedDicts are the typed parameter/result contracts. Inside algorithm execution, all user-facing messaging goes through the `QgsProcessingFeedback` argument and fatal failures raise `QgsProcessingException` (see Rules).
- **`gui/`** — the SPEC §19 defaults-editing surfaces: `widgets.py` (the shared field tables — `default_fields()` / `project_only_fields()` / `layer_fields()`, now *derived* from `params.PARAM_SPECS` / `params.LAYER_VAR_SPECS` so keys, labels and order come from one place — plus the reusable `Override*` scope editors and `OverrideForm`, so pages cannot drift from the parameter/variable schema), `wdg_plugin_options_page.py` (Options page), `wdg_project_options_page.py` (Project Properties page, inheritance-aware), `wdg_layer_options_page.py` (per-layer properties page), and `dlg_layers_table.py` (all-layers table dialog; its vector-only/virtual-only column gating derives from the `LayerVarSpec` flags). Each page's `.ui` skeleton is loaded at module import via `FORM_CLASS, _ = uic.loadUiType(Path(__file__).with_suffix(".ui"))`; the page class inherits `(QgsOptionsPageWidget, FORM_CLASS)` and calls `self.setupUi(self)` in `__init__`, with widget attributes declared as class-level type annotations. `main.py` imports `.gui` lazily inside `initGui` so `qgis_process` never pays the four `.ui` compilations.
- **`toolbelt/`** — a **plugin-agnostic library**: every module here is written to be reusable by any QGIS plugin and carries no dependency on Stratified Packager's identity (`__about__`) or domain logic. Plugin-specific schemas/config live outside it (e.g. `settings.py`'s `StratifiedPackagerSettings`).
  - `logging.py` — `QgisLoggerWrapper` + `QgisHandler` routing each record to `QgsMessageLog`, `QgsMessageBar`, and/or `QMessageBox`. The record-side layer lives in `logging_records.py` (the `Target` `Flag` enum — `LOG | BAR | DIALOG` —, `MessageBarConfig`/`MessageBoxConfig`, `QgisContextFilter`/`TargetFilter`, the `SUCCESS` level and the private sentinel keys) and is re-exported by `logging.py`, so `from .toolbelt.logging import Target` keeps working. Worker-thread emissions are marshalled to the GUI thread automatically via a private `pyqtSignal` with `AutoConnection`. Per-call overrides (`targets=`, `bar_config=`, `box_config=`) ride along inside `extra` under private sentinel keys. Call `.setup()` **once** in `classFactory`, before importing the main plugin module; everywhere else use `QgisLoggerWrapper.get_logger(__name__)`. Exception: Processing algorithm execution messages through `QgsProcessingFeedback` instead (see Rules).
  - `utils.py` — pure-stdlib helpers, **`qgis`-free** (don't import `qgis` here): `sanitize_identifier_name`, `sanitize_filename`, `coerce_bool` (the strict bool coercion every boolean setting/variable shares), `dedupe_names`, `remove_diacritical_marks`, `OperationAbortedError`, `python_executable` (locate the interpreter even when embedded in a host app).
  - `sql.py` — pure-stdlib SQL-text helpers for the SQLite/GeoPackage dialect, **`qgis`-free AND `osgeo`-free** (don't import either here): `quote_identifier` and `safe_table_name` (reserved `gpkg`/`sqlite_` prefix guard). `gpkg.py` (OGR table-drop + `sqlite3` introspection, style/metadata SQL, `wal_session`, `checkpoint_wal`) consumes the quoting; kept separate so they test without `importorskip("osgeo")`.
  - `relations.py` — generic `QgsRelation` graph building + shortest-path finding/pin validation over relation chains (plugin-agnostic; the matching engine consumes it).
  - `zipping.py` — stdlib zip assembly and publishing, **`qgis`-free AND `osgeo`-free**: `build_zip`, `publish_atomic` (chunked abortable copy + `.part`/rename), `sha256_sidecar`, `remove_stale_parts`, `iter_file_members`, `split_archive_path`/`filename_component_error` (strict archive-path validation), `case_insensitive_collisions`.
  - `i18n.py` — `Translatable` Protocol (gives non-`QObject` classes a `tr` classmethod via `QCoreApplication.translate`).
  - `debugging.py` — optional, env-gated `debugpy` bootstrap. `start_debug_server()` (called during plugin initialization) opens a listen socket when `QGIS_DEBUGPY` is truthy (`QGIS_DEBUGPY_HOST`/`_PORT`/`_WAIT` tune it), reading those toggles through `_DebugEnv`, a typed `EnvironmentVariables` subclass from `mapping_proxy.py`. `debugpy` is an optional extra (`[project.optional-dependencies].debugpy`), imported lazily and contained if absent; it passes `utils.python_executable()` to `debugpy.configure(python=...)` because in embedded QGIS `sys.executable` is the host binary, not the interpreter.
  - `mapping_proxy.py` — the **`qgis`-free** foundation the QGIS proxies build on (don't import `qgis` here). Holds: the MRO-aware type-conversion registry (`register_converter` / `to_storage` / `from_storage`) covering `str`/`int`/`float`/`bool`/`list[str]`/`Path`/`datetime`/`date`/`Enum` (QGIS-only types like `QColor` are registered by their owning module, not here); the abstract `MappingProxy` (`MutableMapping`) base giving dict-style typed access (`get(..., cast=)`); and `EnvironmentVariables` — a `MappingProxy` over `os.environ` whose `EnvVar` descriptors (`BoolEnvVar`/`StrEnvVar`/`IntEnvVar`/`FloatEnvVar`/`PathEnvVar`, keyword-only `default`) give typed-attribute access. Touches no QGIS objects, so it's thread-safe; `debugging.py`'s `_DebugEnv` consumes it. Its test module (`test_mapping_proxy.py`) needs no `pytest.importorskip("qgis")` / `pytest.mark.qgis`.
  - `settings.py` — QGIS-specific, type-converting proxies over the disparate QGIS persistence APIs (the *Reading and Storing Settings* cookbook), built on `mapping_proxy.py`'s `MappingProxy` + converter registry. Dict-style **and** typed-descriptor access: `SettingsProxy` (`MutableMapping` over `QgsSettings`) and its schema subclass `PluginSettingsBase` (scoped under `plugins/<slug>`, declares the plugin's keys as `Setting` descriptors — `BoolSetting`/`IntSetting`/`EnumSetting`/… backed by `QgsSettingsEntry*` registered in a per-plugin `QgsSettingsTree` node); `ProjectEntries` (`QgsProject.read*Entry`/`writeEntry`); `ProjectVariables` & `LayerVariables` (`QgsExpressionContextUtils` scopes); `LayerCustomProperties` (`QgsMapLayer.customProperty`). Registers the QGIS-only `QColor` converter into the shared registry at import. **Main-thread-only** (the `QgsSettings`-backed proxies aside). `PluginSettingsBase.teardown()` runs in `main.unload()` to unregister the settings-tree node so plugin reloads re-register cleanly.
- **`tests/`** — mirrors the source tree 1:1: every module in `stratified_packager/` and `scripts/` needs a `test_*.py` at the same relative path. Root `tests/conftest.py` provides the autouse `block_qdialog_exec` fixture (patches `QDialog.exec → DialogCode.Accepted` for `@pytest.mark.qgis` tests so a misconfigured dialog target can't hang CI; non-`qgis` tests skip the patch) plus a `pytest_addoption` that registers inert `qgis_gui_enabled`/`qt_api` ini fallbacks for when `pytest-qgis`/`pytest-qt` are disabled. QGIS-only test modules guard their imports with `pytest.importorskip("qgis")`, so they skip where QGIS is unavailable (and `pytest-qgis` itself errors loudly on autoload if QGIS is missing and the plugin wasn't disabled).
- **`scripts/`** — dev-side tooling that runs *outside* QGIS (uses stdlib `logging`, not `QgisLoggerWrapper`):
  - `customize_qgis_pth.py`: patches `qgis.pth` after `qgis-venv-creator` runs so the venv finds `processing` and GRASS Python.
  - `setup_env_vars.py`: generates `.env` (`QGIS_PROFILES_DIR`, `QGIS_EXECUTABLE_PATH`, `DEVELOPMENT_PROFILE_NAME`, plus the `QGIS_DEBUGPY`/`QGIS_DEBUGPY_WAIT` debug toggles) used by `just deploy` / `just qgis`.
  - `build_qgis_repo_xml.py`: generates `plugins.xml` from `metadata.txt`.
  - `update_metadata.py`, `pylupdate.py`: invoked from prek hooks / `just` recipes — don't call directly.

## Rules (MUST)

1. **Threading (QGIS).**
   - Long-running ops or API calls MUST run in a `QgsTask` so the GUI doesn't freeze.
   - Concurrency-friendly work MUST run across parallel Qt threads whenever that offers non-trivial performance gains over serial flow.
   - NEVER access `QObject`s that live on the main thread (such as `iface`, `QgsProject.instance()`, or any GUI object) from a background thread, as this causes segfaults and silent crashes.
   - NEVER raise exceptions in `QgsTask.run()`. Return `False` to indicate failure instead.
   - Inside the Processing algorithm, parallelism follows SPEC §8: GeoPackage writing runs on the algorithm thread through `QgsVectorFileWriter` (`processing/building.py`) — only the qgis-free zip/move work leaves it, as `processing/workers.py` jobs on a stdlib `ThreadPoolExecutor` (zipfile/shutil/stdlib only; these MUST NOT import `qgis`), with cancellation via a `threading.Event`. Do NOT spawn `QgsTask`s from inside `processAlgorithm` (the task manager is a main-thread QObject whose completion signals need a spinning main event loop that neither `processAlgorithm`'s own worker thread nor `qgis_process` provides).
1. **Cross-version compatibility (QGIS).** Code is written strictly as-if QGIS 4.0+ — no `qgis.core`/`qgis.gui` version shims or behavioral fallbacks (SPEC §1.1 defines the audited support floor and how it is computed from the code; update §1.1 in the same change whenever a new API use moves the floor). The single exception is `qgis.PyQt`: wherever the PyQt6 and PyQt5 idioms differ (e.g. the `QAction` import location), guard with `try:` (PyQt6 idiom) / `except ImportError:` (PyQt5 fallback) and keep the fallback branch import-trivial. Use PyQt6 scoped-enum style everywhere unguarded (valid on PyQt5 5.15).
1. **UI files (QGIS).** Load `.ui` dynamically via `qgis.PyQt.uic.loadUiType`; subclass with docstrings and type annotations on the attributes.
1. **Cleanup (QGIS).** `unload()` MUST remove every GUI element (toolbar, menu, dock widget, layer, action etc) added in `initGui()`, unregister processing providers, disconnect signals and call `.deleteLater()` on any `QObject`s that would otherwise linger indefinitely in memory.
1. **GUI elements (QGIS).**
   - Use `self.iface.mainWindow()` as the parent for `QAction`s and `QDialog`s to ensure proper window management and garbage collection.
   - Set object name on `QAction`s via `action.setObjectName("<unique_name>")` to prevent conflicts with other plugins and enable QGIS to save toolbar customizations.
1. **Custom Processing algorithms (QGIS).**
   - Check `feedback.isCanceled()` at the top of every loop iteration in `processing` algorithms and other worker threads. Failure to check causes unresponsive cancellation.
   - Report progress in `processing` algorithms using `feedback.setProgress()` with a percentage (0-100).
   - All user-facing messaging inside algorithm execution (`processAlgorithm` and every helper it calls) goes through the `QgsProcessingFeedback` passed by the framework — `pushInfo`, `pushWarning`, `pushDebugInfo`, `pushCommandInfo`, `pushConsoleInfo`, `pushFormattedMessage`, `reportError`, `setProgressText` — NEVER `QgisLoggerWrapper`: the wrapper lands in `QgsMessageLog`/GUI targets, which the algorithm's log panel and `qgis_process` output don't show. Level mapping when porting log calls: debug → `pushDebugInfo`, info → `pushInfo`, warning → `pushWarning`, error → `reportError`, critical → raise `QgsProcessingException`.
   - On fatal failure inside algorithm execution, raise `QgsProcessingException` with a `self.tr(...)` message (`raise ... from err` when wrapping a foreign exception) — the framework's sanctioned failure path (see *Exception containment*).
   - Helpers invoked during algorithm execution take `feedback: QgsProcessingFeedback` as an explicit parameter (consistent with *No global mutable state*).
   - Declare all outputs in `initAlgorithm()`. Undeclared outputs are invisible to the Processing framework and cannot be used in models or chains.
   - NEVER give a `QgsProcessingParameterMultipleLayers` a `defaultValue` (see `LAYERS` in `params.declare_parameters`). Its widget wrapper does not round-trip layer identity: `setWidgetValue` resolves whatever default it is given to layers and stores each one's **data source** string, so the algorithm receives sources, not ids. Because `QgsProcessingUtils.mapLayerFromString` matches id, then name, then source, every string of a shared source resolves to the same first-matching layer — silently collapsing layers that share a source (SPEC §12) onto one member, repeated, and dropping the rest from the run. Left defaultless the wrapper never rewrites: an untouched widget sends nothing (the runtime fallback resolves it) and an opened picker stores `layer->id()` per row. The same trap applies to any parameter resolved through `mapLayerFromString`: identify layers by **id**, never by source, whenever two project layers may share one.
1. **CRS (QGIS).** Never string-match CRSs (authids/proj4). For "are these the same CRS?" questions (keying, reporting, equality-as-information), compare via `pyproj.CRS` objects. For "do I need to transform?" decisions, let the `QgsCoordinateTransform` decide (`isShortCircuited()`) rather than pre-comparing. Never silently reproject — log source and target CRS on every transform.
1. **i18n (QGIS).** Every user-facing string, including logs, combobox option labels, debug messages and exception messages, MUST go through `self.tr(...)`. Sole exception: the Processing run dialog's enum options stay raw SPEC tokens — the static-string `QgsProcessingParameterEnum` makes the shown text the stored/CLI value, so translating it would break the token contract; the SPEC §19 defaults-GUI combos instead show translated labels and store the token (`FieldSpec.labeled_choices`, read back via `currentData()`). Non-`QObject` classes inherit `Translatable` (gives a `tr` classmethod). Module-level user-facing strings call `QCoreApplication.translate(...)` directly. `QT_TRANSLATE_NOOP` extraction sites MUST spell the context as a string literal, never a variable — `pylupdate` statically parses the context argument and silently drops messages whose context is not a literal (the runtime `translate(...)` call may still use a constant like `params._ALG`). Any message interpolating an integer that may need singular vs. plural wording uses the `%n` placeholder with the count argument (`self.tr("%n stratum(s)", n=count)`, or `QCoreApplication.translate(ctx, "%n …", None, count)`) — and because `pylupdate` may emit such a message **without** `numerus="yes"`, every `%n` entry MUST carry `numerus="yes"` in the `.ts` — the pylupdate hook auto-adds it (and a `<numerusform>`) to every newly-written `%n` message, and fails only if a *pre-existing* entry still lacks it (hand-fix: add the attribute and its `<numerusform>` entries, then rerun).
1. **Logging.** Plugin code uses `QgisLoggerWrapper` — except inside Processing algorithm execution, which messages exclusively through `QgsProcessingFeedback` (see *Custom Processing algorithms*); tests and `scripts/` use stdlib `logging`. The `print()` function is only allowed in `if __name__ == "__main__":` sections, but still discouraged.
1. **Exception containment.** No exception (raised directly or via a callee) may escape the plugin's code boundary. Catch it, then log at `WARNING`+ scaled to how disruptive it is. Prefer to document it with `:raise ...:` in the function/module docstring, propagate, and handle at the shallowest frame whose caller would be outside plugin code; handle locally only when exceptions-as-control-flow is clearer. `QgsProcessingException` raised during algorithm execution is exempt: propagating it out of `processAlgorithm` *is* the boundary handling — the Processing framework catches and reports it.
1. **Success flags.** Every PyQGIS/PyQt callable that returns a success/`bool` flag MUST have it checked. When failure blocks the current callable, `raise` (to be handled at a shallower frame), but if already at a boundary/top-level frame, log at `WARNING`+.
1. **No global mutable state.** Pass configuration as function arguments.
1. **Paths.** `pathlib.Path` everywhere — no `os.path`, no string concatenation. Resolve via `QgsProject.instance().readPath()`, `Path(__file__).with_suffix(".ui")`, etc. Concatenate literal subpaths like `Path(prefix) / "a/b/c"`, not `Path(prefix) / "a" / "b" / "c"`.
1. **Suppression comments.** Any `# noqa`, `# type: ignore`, `# ty: ignore`, or `# pylint: disable` must carry a comment explaining why.
1. **Runnable scripts.** Module-level executable code is guarded with `if __name__ == "__main__":`.
1. **English only** in the repository (identifiers, literals, docstrings, comments, file names) — `.ts` translation files excepted.
1. **Verify, don't trust**: When producing an analysis or summarization of something gleaned from a resource (web page, MCP call, user-provided document), do not trust a memory or retained summary of that resource. Always retrieve the resource afresh and compare it to the summary or analysis you are preparing. When comparing, do so in an adversarial way: you are fact-checking work that you suspect at the start contains errors and hallucinations.
1. **Commit messages** follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/): `<type>[optional scope][!]: <description>`, then an optional blank-line-separated body, then optional footers (`Token: value`, `-` in place of spaces in tokens). `feat` = new feature (SemVer MINOR); `fix` = bug fix (PATCH); other types as fitting — `build`, `chore`, `ci`, `docs`, `perf`, `refactor`, `style`, `test`. Scope = the touched area in parentheses (e.g. `processing`, `toolbelt`, `gui`, `i18n`, `just`). A breaking change MUST carry `!` immediately before the `:` and/or an uppercase `BREAKING CHANGE: <description>` footer. Description: imperative, ≤ 72 chars, no trailing period.

## Style (SHOULD)

### Design

- Prefer strict fail-fast semantics over silent fallbacks (e.g. abort on NULL stratum names or name collisions rather than guessing).
- Push evaluation to the provider/C++ side (filter expressions, prepared geometry engines) instead of per-feature Python.
- Surface configuration through idiomatic QGIS UI locations (Options / Project Properties / Layer Properties pages) rather than custom dialogs.

### Imports & dependencies

- Standard imports: `from qgis.core import ...`, `from qgis.PyQt.QtGui import ...`.
- Intra-package sibling imports are relative (`from .logging import QgisLoggerWrapper`); the package root `__init__.py` uses absolute paths.
- Allowed deps in the plugin: `qgis` + vendored `PyQt6` + `processing` + `GDAL` + `pyproj`. Acceptable QGIS-bundled extras when they materially improve perf or maintainability: `geopandas`, `lxml`, `numpy`, `pydantic`, `pyogrio`, `PyOpenGL`, `requests`, `scipy`, `shapely`, `tzdata`.
- Line length 99 (soft-limit; `ruff` enforces in Python).

### Naming

- `CamelCase` classes, `SCREAMING_SNAKE_CASE` constants, `snake_case` everything else — except names overriding PyQGIS/PyQt (e.g. `loadAlgorithms`, `processAlgorithm`) or expected verbatim by QGIS (`classFactory`, `initGui`, `initProcessing`).

### Strings & locals

- Logging uses `%`-style with deferred interpolation: `log.info(self.tr("Loaded %s"), name)`.
- Other user-facing text calls `.format()` on the translated string: `self.tr("Loaded {}").format(name)`.
- Everywhere else, prefer f-strings.
- Don't assign a local variable used only once unless it materially improves readability or has a side-effect that must occur before use.

### Typing (`mypy` + `ty`; settings in `pyproject.toml`)

- Annotate everywhere, including tests, except obviously-typed locals (e.g. `len = 3.5`, `path = Path("str_path")`).
- Postel's Law — parameters take abstract protocols (`Iterable[float]`, `Sequence[int]`, `Mapping[str, bool]`, `StrPath`); return types are specific.
- `if TYPE_CHECKING:` for imports and definitions used only by static checkers.
- Use type aliases, explicit `@override`, `Protocol`, `ParamSpec`, `TypedDict` where they fit.
- Help checkers narrow return types via generics or overloads when more than one return type is possible.
- `ClassVar` for class variables, `Final` for constants.
- ty's `respect-type-ignore-comments = false` disables only mypy-style `# type: ignore`, not ty's own `# ty: ignore[code]` — use the latter for ty. A directly-imported uninstalled optional dep (e.g. `debugpy`) also needs a mypy `ignore_missing_imports` override.

### Docstrings (Sphinx 9.1+; assume `sphinx-autodoc-typehints`)

- Fields: `param`, `return` (when not `None`), `yield` (when applicable), `raise` (one per known exception). Don't write `type` / `rtype` / `ytype`.
- Single-line docstrings stay single-line when they fit in ≤ 99 chars.
- Multi-line: 4-space indent, lines wrap at 90 chars; first line is a ≤ 99-char short description ending in a period, followed by a blank line; imperative mood for callables (not required for tests).
- Single spaces between sentences on the same line. Don't use double space before starting a new sentence.
- Use Sphinx roles (`:mod:`, `:exc:`, `:class:`, `:attr:`, `:meth:`, `:func:`, `:data:`, ...) for identifier references.
- Class / instance / module attributes get their own docstrings — don't document them inside the parent's docstring.
- `__init__` parameters are described in the method's docstring, not the class'.
- Prefer docstrings over comments. Comments only for local scope and non-obvious execution logic.

## Tests

- Stack: `pytest≥9.1`, `pytest-cov≥7.1`, `pytest-qgis≥4`, `pytest-qt≥4.5`, `hypothesis≥6.156` — use them where they fit. Config lives under `[tool.pytest]` / `[tool.coverage]` in `pyproject.toml`.
- Tests requiring QGIS at runtime must be marked `@pytest.mark.qgis` (the autouse `block_qdialog_exec` fixture only patches `QDialog.exec` for these) and guard their module-level QGIS imports with `pytest.importorskip("qgis")` so they skip where QGIS is unavailable. To run the suite without QGIS, disable the plugins that need it: `-p no:pytest_qgis -p no:pytest-qt` (leaving `pytest-qgis` enabled when QGIS is missing makes it error loudly on autoload).
- `tests/e2e/` (marker `e2e`) drives the `qgis_process` CLI as a subprocess against the committed fixture project in `tests/fixtures/e2e/` (`.qgs` + `.geojsonl`, relative paths) — provider registration, headless `--PROJECT_PATH` defaults, zip/report assertions via stdlib `zipfile`/`sqlite3`. It never imports `qgis` in-process and self-skips when no `qgis_process` is discoverable (PATH, `QGIS_EXECUTABLE_PATH`/.env, or the venv's `qgis` package location), so it runs in every QGIS CI job with no extra wiring.
- **Binding independence.** Tests assert behaviour — return values, exceptions, side effects — through `qgis.PyQt`, so the same test passes on PyQt6 (QGIS 4.0+) and PyQt5 (QGIS 3.40/3.44); CI runs both. Let the callable resolve its own `try:`/`except ImportError:` fallback (don't pin a test to one binding's import path or enum spelling); replicate the fallback in the test only when the divergence can't be hidden. When a behaviour exists only on the newer version, gate the test with `pytest.mark.skipif` rather than forking the assertion — e.g. `skip_if_no_unaccent` in `tests/stratified_packager/toolbelt/test_i18n.py`.
- Parametrize rather than duplicating near-identical test functions.
- Target ≥ 80% coverage overall, ≥ 90% on core plugin logic. Don't pad with low-value tests — evaluate signal per new test.
- Do not use mock data that bypasses the actual validation logic.

## Commands

All routine tasks go through `just` (`just` with no args lists everything, grouped). Recipes shell out via `uv run`, picking up the QGIS-aware venv.

```text
# QA — chains format → lint → type-check
just qa
just format        # ty --fix, ruff --fix, ruff format
just lint          # ruff check, flake8, pylint .
just type-check    # ty check, mypy .

# Tests — args forward to pytest; --cov is on by default
just test
just test -m "not qgis"                                       # skip QGIS tests (QGIS present)
just test tests/stratified_packager/test___about__.py::test_x # single test
just test -k pattern                                          # by pattern
just serve-cov [PORT] / just browse-cov [PORT]                # htmlcov/

# Pre-commit (prek, NOT pre-commit)
just install-hooks
just prek                # all hooks on the tree
just prek <hook-id>      # single manual hook, e.g. sync-with-uv

# Dependencies
just lock                # uv lock --upgrade
just sync                # uv sync --frozen
# After changing pins in pyproject.toml, run the sync-with-uv prek hook
# to mirror them into .pre-commit-config.yaml.

# Docs
just build-docs [html|latexpdf]
just serve-docs [PORT] / just browse-docs [PORT]

# i18n
just lupdate                       # regenerates .ts via pylupdate prek hook
just lrelease                      # compiles .ts -> .qm via pyside6-lrelease (pulls pyside6-essentials)

# Run the plugin in QGIS — env vars from .env (created by `just setup-env-vars`):
#   QGIS_PROFILES_DIR, QGIS_EXECUTABLE_PATH, DEVELOPMENT_PROFILE_NAME
just deploy [profile]   # mirror source into $QGIS_PROFILES_DIR/<profile>/python/plugins/stratified_packager
just qgis   [profile]   # launch QGIS with profile
just run    [profile]   # deploy + qgis

# Packaging / release
just package       # wraps qgis-plugin-ci package
just build-xml     # plugins.xml from metadata.txt
```

## First-time setup

The venv is created via `qgis-venv-creator` (not plain `uv venv`) so it inherits the QGIS Python's site-packages and picks up `qgis.pth`. `scripts/customize_qgis_pth.py` then patches `qgis.pth` to add the QGIS plugins directory and the GRASS Python directory.

`qgis-venv-creator` is third-party and its platform support is uneven: only its `Windows` backend accepts `--qgis-installation` / `--python-executable`; the `Linux` backend ignores any installation path and just builds a `--system-site-packages` venv from `python3` on `PATH`; **macOS (Darwin) is unsupported** (raises `UnsupportedPlatformError`). Hence `just create-venv <prefix>` only consumes `<prefix>` on Windows (Linux ignores it; macOS can't run it), and there is no macOS CI job.

```powershell
# Provisions scoop/git/just/pwsh, then runs `just bootstrap`:
powershell -ExecutionPolicy Bypass -File .\scripts\venv_setup.ps1 "C:\Program Files\QGIS 3.40.15\apps\qgis-ltr"

# Or, if uv + just are already installed:
just bootstrap "C:\Program Files\QGIS 3.40.15\apps\qgis-ltr"
```

`just bootstrap` chains: `install-uv` → `create-venv` → `setup-env-vars` → `install-debugpy` → `customize-pth` → `install-hooks`.
