# Managing translations

User-facing strings go through `self.tr(...)` (either from `QObject` or
`toolbelt.i18n.Translatable`) or directly through `QCoreApplication.translate(...)` if not inside
a class. English is the source language, so it needs no catalog (Qt falls back to the source
string). The translations are collected into Qt translation files under
`stratified_packager/resources/i18n/`:

- `stratified_packager_es.ts` — neutral international Spanish (serves every `es*` locale)
- `stratified_packager_pt.ts` — Brazilian Portuguese

The `.ts` files are XML and tracked in git; the compiled `.qm` files are binary,
git-ignored, and produced by CI (see below).

## Update the `.ts` files from the source

```powershell
just lupdate
```

This runs the `pylupdate` prek hook, which calls `scripts/pylupdate.py` — a wrapper around
`PyQt6.lupdate` that extracts translatable strings from the `.py` and `.ui` files and writes them
into the `.ts` files with POSIX-relative source locations (`--no-obsolete`, so obsolete entries are
dropped). The same hook also runs automatically on commit whenever a `.py` or `.ui` file changes.

> There is no `.pro` profile file and no `pylupdate5`; `scripts/pylupdate.py` replaces both.

## Translate

Edit the `.ts` files directly (they are plain XML) or open them in **Qt Linguist**. To add
a language, create a new `stratified_packager_<lang>.ts` file in the same directory — the
hook's `*.ts` glob picks it up automatically.

## Compile to `.qm`

Compilation is handled by the `publishing.yml` workflow, which installs Qt's `lrelease`
(the `qt6-l10n-tools` package), compiles every `.ts` to `.qm`, and bundles the result into
the released package.

To compile locally, run `just lrelease`. It uses `pyside6-lrelease` (pulled on demand via
`uv run --with pyside6-essentials`, since QGIS ships no `lrelease` CLI of its own) to write a
`.qm` next to each `.ts`. The `.qm` files are git-ignored; CI regenerates them at release time.
