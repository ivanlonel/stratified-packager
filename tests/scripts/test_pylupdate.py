"""
Tests for :mod:`scripts.pylupdate`.

The wrapper builds on :mod:`PyQt6.lupdate`, which belongs to the ``pack`` dependency group
(and the QGIS-bundled stack) rather than the ``test`` group, so the whole module is skipped
where that API is unavailable. The heavy Qt parsing is stubbed; these tests cover the
wrapper's own logic — glob expansion, the POSIX-relative ``location`` override, source-type
dispatch, the ``%n``/``numerus`` post-check, and the CLI return codes.

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/scripts/test_pylupdate.py
"""
# pylint: disable=redefined-outer-name  # pytest fixtures are used as test parameters by design

from __future__ import annotations

import argparse
import sys
import types
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock
from xml.etree import ElementTree as ET

import pytest

pytest.importorskip("PyQt6.lupdate.translation_file", reason="The wrapper subclasses this API.")
pytest.importorskip("PyQt6.lupdate.user", reason="UserException lives here.")

# Imported only after the importorskip guards above confirm the PyQt6.lupdate API is available.
from PyQt6.lupdate.user import UserException

from scripts import pylupdate as mod

if TYPE_CHECKING:
    from pathlib import Path

    from PyQt6.lupdate.translations import Message


def _main_argv(ts: Path, source: Path, *extra: str) -> list[str]:
    r"""
    Build a ``sys.argv`` for :func:`main` with the required ``--ts`` and source file.

    The ``--`` separator keeps the ``--ts`` (``nargs="+"``) option from swallowing the
    positional source file.

    :param ts: Path to the ``.ts`` translation file (must exist for glob expansion).
    :param source: Path to the source file (must exist for glob expansion).
    :param \*extra: Extra option strings inserted before the source file.
    :return: An ``argv`` list, including the program name at index 0.
    """
    return ["pylupdate", "--ts", str(ts), *extra, "--", str(source)]


# ---------------------------------------------------------------------------
# _AppendGlob
# ---------------------------------------------------------------------------


class TestAppendGlob:
    """Tests for the :class:`_AppendGlob` argparse action."""

    def test_expands_glob_to_matches(self, tmp_path: Path) -> None:
        """A glob pattern must expand to every matching path."""
        (tmp_path / "a.py").write_text("", encoding="utf-8")
        (tmp_path / "b.py").write_text("", encoding="utf-8")
        parser = argparse.ArgumentParser()
        parser.add_argument("files", nargs="+", action=mod._AppendGlob)
        namespace = parser.parse_args([str(tmp_path / "*.py")])
        assert set(namespace.files) == {tmp_path / "a.py", tmp_path / "b.py"}

    def test_no_match_calls_parser_error(self, tmp_path: Path) -> None:
        """
        A pattern matching nothing must abort via ``parser.error``
        (:exc:`~builtins.SystemExit`).
        """
        parser = argparse.ArgumentParser()
        parser.add_argument("files", nargs="+", action=mod._AppendGlob)
        with pytest.raises(SystemExit):
            parser.parse_args([str(tmp_path / "*.nomatch")])

    def test_single_string_value_is_treated_as_one_pattern(self, tmp_path: Path) -> None:
        """A scalar (non-list) option value must be handled as a single pattern."""
        (tmp_path / "x.ui").write_text("", encoding="utf-8")
        parser = argparse.ArgumentParser()
        parser.add_argument("--one", action=mod._AppendGlob)
        namespace = parser.parse_args(["--one", str(tmp_path / "x.ui")])
        assert namespace.one == [tmp_path / "x.ui"]


# ---------------------------------------------------------------------------
# MyTranslationFile._make_location_el
# ---------------------------------------------------------------------------


class TestMakeLocationEl:
    """Tests for :meth:`MyTranslationFile._make_location_el`."""

    def test_location_uses_posix_relative_path(self, tmp_path: Path) -> None:
        """The ``filename`` attribute must be POSIX and relative to the ``.ts`` directory."""
        ts = tmp_path / "i18n/app_pt.ts"
        ts.parent.mkdir(parents=True)
        source = tmp_path / "src/module.py"
        source.parent.mkdir()

        # `_make_location_el` reads only `self._ts_file`, so call it unbound on a stand-in to
        # bypass `TranslationFile.__init__` (it reads a real .ts).
        translation = cast("mod.MyTranslationFile", types.SimpleNamespace(_ts_file=str(ts)))
        message = types.SimpleNamespace(filename=str(source), line_nr=42)

        element = mod.MyTranslationFile._make_location_el(translation, cast("Message", message))
        assert element.tag == "location"
        assert element.get("filename") == "../src/module.py"
        assert element.get("line") == "42"


# ---------------------------------------------------------------------------
# MyTranslationFile._make_message_el
# ---------------------------------------------------------------------------


def _fake_message(source: str, *, numerus: bool) -> Message:
    """
    Build a stand-in :class:`~PyQt6.lupdate.translations.Message` for ``_make_message_el``.

    :param source: The message source text.
    :param numerus: Whether the parser flagged the call as plural.
    :return: An object exposing the attributes ``_make_message_el`` reads.
    """
    embedded = types.SimpleNamespace(message_id="", extra_comments=[], extras=[])
    message = types.SimpleNamespace(
        source=source, comment="", numerus=numerus, embedded_comments=embedded
    )
    return cast("Message", message)


class TestMakeMessageEl:
    """Tests for :meth:`MyTranslationFile._make_message_el` numerus coercion."""

    @pytest.fixture
    def translation_file(self, tmp_path: Path) -> mod.MyTranslationFile:
        """Return a real, empty translation file (its ``.ts`` is absent, so it starts blank)."""
        return mod.MyTranslationFile(
            str(tmp_path / "absent.ts"), no_obsolete=True, no_summary=True, verbose=False
        )

    @pytest.mark.parametrize(
        ("source", "numerus", "expect_numerus"),
        [
            pytest.param("%n file(s)", False, True, id="percent-n-undetected-is-coerced"),
            pytest.param("%n file(s)", True, True, id="percent-n-detected-stays"),
            pytest.param("plain message", False, False, id="no-percent-n-untouched"),
        ],
    )
    def test_forces_numerus_for_percent_n_sources(
        self,
        translation_file: mod.MyTranslationFile,
        source: str,
        numerus: bool,
        expect_numerus: bool,
    ) -> None:
        """Any new ``%n`` message gains ``numerus="yes"`` and exactly one ``<numerusform>``."""
        element = translation_file._make_message_el(_fake_message(source, numerus=numerus))
        assert (element.get("numerus") == "yes") is expect_numerus
        numerusforms = element.findall("translation/numerusform")
        assert len(numerusforms) == (1 if expect_numerus else 0)

    def test_end_to_end_autofix_over_real_source(self, tmp_path: Path) -> None:
        """
        A ``%n`` call the parser cannot flag as plural still lands with numerus markup.

        ``translate("Ctx", "%n item(s)")`` carries no count argument, so the parser sets
        ``numerus=False``; the override must still write ``numerus="yes"`` (and
        ``_check_numerus`` must therefore not raise).
        """
        source = tmp_path / "widget.py"
        source.write_text('translate("Ctx", "%n item(s)")\n', encoding="utf-8")
        ts = tmp_path / "app.ts"

        mod.lupdate([source], [ts])  # must not raise UserException

        # S314: parsing a .ts file `lupdate` itself just wrote into tmp_path, not untrusted input.
        (message_el,) = ET.parse(ts).getroot().iter("message")  # noqa: S314
        assert message_el.findtext("source") == "%n item(s)"
        assert message_el.get("numerus") == "yes"
        assert message_el.find("translation/numerusform") is not None


# ---------------------------------------------------------------------------
# lupdate
# ---------------------------------------------------------------------------


class TestLupdate:
    """Tests for :func:`lupdate` source dispatch and exclude handling."""

    def test_dispatches_py_and_ui_sources(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``.py`` files go to ``PythonSource`` and ``.ui`` files to ``DesignerSource``."""
        recorded_py: list[Path] = []
        recorded_ui: list[Path] = []
        translation = MagicMock()

        def fake_python(*, filename: Path, verbose: bool) -> MagicMock:
            assert verbose is False
            recorded_py.append(filename)
            return MagicMock()

        def fake_designer(*, filename: Path, verbose: bool) -> MagicMock:
            assert verbose is False
            recorded_ui.append(filename)
            return MagicMock()

        monkeypatch.setattr(mod, "PythonSource", fake_python)
        monkeypatch.setattr(mod, "DesignerSource", fake_designer)
        monkeypatch.setattr(mod, "MyTranslationFile", lambda *_a, **_k: translation)
        # The mocked MyTranslationFile writes no file for the post-check to read.
        monkeypatch.setattr(mod, "numerus_violations", lambda _paths: [])

        py = tmp_path / "a.py"
        py.write_text("", encoding="utf-8")
        ui = tmp_path / "b.ui"
        ui.write_text("", encoding="utf-8")

        mod.lupdate([py, ui], [tmp_path / "t.ts"])

        assert recorded_py == [py]
        assert recorded_ui == [ui]
        assert translation.update.call_count == 2
        translation.write.assert_called_once()

    def test_directory_is_recursed_with_excludes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Directory sources recurse, honouring excludes and ignoring non-source files."""
        collected: list[Path] = []

        def fake_source(*, filename: Path, verbose: bool) -> MagicMock:
            assert verbose is False
            collected.append(filename)
            return MagicMock()

        monkeypatch.setattr(mod, "PythonSource", fake_source)
        monkeypatch.setattr(mod, "DesignerSource", fake_source)
        monkeypatch.setattr(mod, "MyTranslationFile", lambda *_a, **_k: MagicMock())
        # The mocked MyTranslationFile writes no file for the post-check to read.
        monkeypatch.setattr(mod, "numerus_violations", lambda _paths: [])

        pkg = tmp_path / "pkg"
        (pkg / "sub").mkdir(parents=True)
        keep = pkg / "keep.py"
        keep.write_text("", encoding="utf-8")
        skip = pkg / "sub/skip.py"
        skip.write_text("", encoding="utf-8")
        (pkg / "notes.md").write_text("", encoding="utf-8")  # neither .py nor .ui

        mod.lupdate([pkg], [tmp_path / "t.ts"], excludes=["sub"])

        assert keep in collected
        assert skip not in collected

    def test_directory_scan_order_is_sorted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Directory sources are consumed in sorted POSIX-path order, not filesystem order."""
        collected: list[Path] = []

        def fake_source(*, filename: Path, verbose: bool) -> MagicMock:
            assert verbose is False
            collected.append(filename)
            return MagicMock()

        monkeypatch.setattr(mod, "PythonSource", fake_source)
        monkeypatch.setattr(mod, "DesignerSource", fake_source)
        monkeypatch.setattr(mod, "MyTranslationFile", lambda *_a, **_k: MagicMock())
        # The mocked MyTranslationFile writes no file for the post-check to read.
        monkeypatch.setattr(mod, "numerus_violations", lambda _paths: [])

        pkg = tmp_path / "pkg"
        (pkg / "sub").mkdir(parents=True)
        # Created deliberately out of sorted order.
        for name in ("zeta.py", "sub/beta.ui", "alpha.py", "sub/aleph.py"):
            (pkg / name).write_text("", encoding="utf-8")

        mod.lupdate([pkg], [tmp_path / "t.ts"])

        assert collected == sorted(collected, key=lambda p: p.as_posix())
        assert len(collected) == 4

    def test_unsupported_source_raises_user_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A source that is not a directory, ``.py`` or ``.ui`` must raise :exc:`UserException`."""
        monkeypatch.setattr(mod, "MyTranslationFile", lambda *_a, **_k: MagicMock())
        bad = tmp_path / "data.txt"
        bad.write_text("", encoding="utf-8")
        with pytest.raises(UserException):
            mod.lupdate([bad], [tmp_path / "t.ts"])


# ---------------------------------------------------------------------------
# numerus_violations
# ---------------------------------------------------------------------------

_TS_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="pt_BR">
<context>
  <name>Ctx</name>
  <message{numerus}>
    <source>{source}</source>
    <translation type="unfinished"></translation>
  </message>
</context>
</TS>
"""


class TestNumerusViolations:
    """Tests for :func:`numerus_violations` and its wiring into :func:`lupdate`."""

    @pytest.mark.parametrize(
        ("numerus", "source", "expected"),
        [
            pytest.param("", "%n file(s)", 1, id="percent-n-without-numerus"),
            pytest.param(' numerus="yes"', "%n file(s)", 0, id="percent-n-with-numerus"),
            pytest.param("", "plain message", 0, id="no-percent-n"),
        ],
    )
    def test_detects_percent_n_messages_missing_numerus(
        self, tmp_path: Path, numerus: str, source: str, expected: int
    ) -> None:
        """Only ``%n`` messages lacking ``numerus="yes"`` are reported."""
        ts = tmp_path / "app_pt.ts"
        ts.write_text(_TS_TEMPLATE.format(numerus=numerus, source=source), encoding="utf-8")
        violations = mod.numerus_violations([ts])
        assert len(violations) == expected
        if expected:
            assert "Ctx" in violations[0]
            assert source in violations[0]

    def test_lupdate_raises_on_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fail :func:`lupdate` with :exc:`UserException` when a written file violates."""
        monkeypatch.setattr(mod, "MyTranslationFile", lambda *_a, **_k: MagicMock())
        monkeypatch.setattr(mod, "numerus_violations", lambda _paths: ["app_pt.ts: ..."])
        source = tmp_path / "a.py"
        source.write_text("", encoding="utf-8")
        with pytest.raises(UserException, match="numerus"):
            mod.lupdate([source], [tmp_path / "t.ts"])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for the :func:`main` CLI entry point and its return codes."""

    @pytest.fixture
    def ts_and_source(self, tmp_path: Path) -> tuple[Path, Path]:
        """
        Create an existing ``.ts`` file and ``.py`` source so glob expansion succeeds.

        :param tmp_path: Per-test temporary directory.
        :return: A ``(ts_path, source_path)`` tuple.
        """
        ts = tmp_path / "app.ts"
        ts.write_text("", encoding="utf-8")
        source = tmp_path / "a.py"
        source.write_text("", encoding="utf-8")
        return ts, source

    def test_returns_zero_on_success(
        self,
        ts_and_source: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A successful run must return ``0``."""
        ts, source = ts_and_source
        monkeypatch.setattr(mod, "lupdate", lambda *_a, **_k: None)
        monkeypatch.setattr(sys, "argv", _main_argv(ts, source))
        assert mod.main() == 0

    def test_returns_one_on_user_exception(
        self,
        ts_and_source: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A :exc:`UserException` from ``lupdate`` must be reported and return ``1``."""
        ts, source = ts_and_source
        monkeypatch.setattr(mod, "lupdate", MagicMock(side_effect=UserException("bad source")))
        monkeypatch.setattr(sys, "argv", _main_argv(ts, source))
        assert mod.main() == 1

    def test_returns_two_on_unexpected_error(
        self,
        ts_and_source: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An unexpected error without ``--verbose`` must return ``2`` and print a notice."""
        ts, source = ts_and_source
        monkeypatch.setattr(mod, "lupdate", MagicMock(side_effect=RuntimeError("kaboom")))
        monkeypatch.setattr(sys, "argv", _main_argv(ts, source))
        assert mod.main() == 2
        assert "unexpected" in capsys.readouterr().err.lower()

    def test_verbose_unexpected_error_prints_traceback(
        self,
        ts_and_source: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """With ``--verbose`` an unexpected error must still return ``2`` but print a traceback."""
        ts, source = ts_and_source
        monkeypatch.setattr(mod, "lupdate", MagicMock(side_effect=RuntimeError("kaboom")))
        monkeypatch.setattr(sys, "argv", _main_argv(ts, source, "--verbose"))
        assert mod.main() == 2
        assert "Traceback" in capsys.readouterr().err
