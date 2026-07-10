# Testing the plugin

Tests live under `tests/`, mirroring the source tree 1:1 — every module in
`stratified_packager/` and `scripts/` has a `test_*.py` at the same relative path.
Tests that need a running QGIS are marked `@pytest.mark.qgis` and guard their imports with
`pytest.importorskip("qgis")`, so they skip cleanly where QGIS is unavailable.

The test stack ([`pytest`](https://pytest.org/),
[`pytest-cov`](https://github.com/pytest-dev/pytest-cov),
[`pytest-qgis`](https://github.com/osgeosuomi/pytest-qgis),
[`pytest-qt`](https://github.com/pytest-dev/pytest-qt),
[`hypothesis`](https://hypothesis.readthedocs.io/)) is managed with **uv** and configured
under `[tool.pytest]` / `[tool.coverage]` in `pyproject.toml`.
Routine runs go through **just** (which shells out via `uv run`):

```bash
# all tests, with coverage (--cov is on by default)
just test

# a single module, or a single test
just test tests/stratified_packager/test___about__.py
just test tests/stratified_packager/test___about__.py::test_version_semver

# select by keyword
just test -k pattern
```

## Coverage

Coverage is collected by default (`--cov` is configured under `[tool.pytest]` in
`pyproject.toml`) and an HTML report is written to `htmlcov/`. Browse it with:

```bash
just serve-cov [PORT]    # serve htmlcov/ (default port 8080)
just browse-cov [PORT]   # open http://localhost:PORT
```

Aim for ≥ 80% coverage overall and ≥ 90% on core plugin logic.

## Full local gate

`just check` (alias `just ci`) runs the whole gate — all QA checks (`just qa`) followed by
the test suite. Run it before pushing.

## PyQt5 / PyQt6

QGIS wraps whichever Qt binding the host ships — PyQt6 on QGIS 4.0+, PyQt5 on the 3.x LTRs —
behind `qgis.PyQt`. The CI matrix runs the suite on both (PyQt5: QGIS 3.40/3.44; PyQt6:
QGIS 4.0+), so a test that passes locally must pass under either binding.

Write tests against behaviour (return values, exceptions, side effects) through `qgis.PyQt`, not
against a specific binding's import path or enum spelling. Let the callable resolve its own
`try:`/`except ImportError:` fallback; replicate that fallback in the test only when the divergence
can't be hidden. When a behaviour exists only on the newer version, skip the test on older ones
with `pytest.mark.skipif` (see `skip_if_no_unaccent` in `test_i18n.py`) rather than forking the
assertion.

## Running without QGIS

`pytest-qgis` and `pytest-qt` import `qgis` / `PyQt6` at load time, so in an environment
without a QGIS/Qt runtime they must be disabled or they fail on autoload. Disable both and the
QGIS-marked modules skip via `importorskip`:

```bash
just test -p no:pytest_qgis -p no:pytest-qt
```

Leaving `pytest-qgis` enabled when QGIS is missing makes it error loudly on autoload — that is
intentional, so an absent or broken QGIS is never silently skipped.
