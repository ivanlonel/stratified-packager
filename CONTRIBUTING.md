# Contributing Guidelines

First off, thanks for considering contributing to this project!

These are mostly guidelines, not rules. Use your best judgment, and feel free to propose
changes to this document in a pull request.

## Getting set up

Development tasks run through [`just`](https://just.systems) on **PowerShell 7**, with
dependencies managed by [`uv`](https://docs.astral.sh/uv/) in a QGIS-aware virtual
environment. From a fresh clone:

```powershell
just bootstrap "C:\Program Files\QGIS 3.40.15\apps\qgis-ltr"
```

On Windows, `scripts/venv_setup.ps1` can provision the prerequisites (`uv`, `just`, `pwsh`)
for you first. See the [Development environment guide](docs/development/environment.md)
for the full walkthrough.

## Git hooks

Quality checks are enforced with git hooks managed by [prek](https://github.com/j178/prek)
(a drop-in pre-commit replacement). `just bootstrap` installs them; you can also run
`just install-hooks`. To run every hook against the whole tree:

```powershell
just prek
```

The hook configuration lives in `.pre-commit-config.yaml`.

## Code style and checks

Code is formatted and checked automatically:

- **Formatting & linting**: [`ruff`](https://docs.astral.sh/ruff/) (format + lint), plus
  [`flake8`](https://flake8.pycqa.org/) and [`pylint`](https://www.pylint.org/).
- **Type checking**: [`mypy`](https://mypy-lang.org/) and [`ty`](https://docs.astral.sh/ty/).
- **Docstrings**: Sphinx style.

Run them all with `just qa` (format → lint → type-check), and the full gate — QA plus
tests — with `just check` before pushing. The project's detailed coding rules are
documented in `CLAUDE.md`.

## Tests

```powershell
just test
```

See the [Testing guide](docs/development/testing.md) for coverage, markers, and running
without QGIS.
