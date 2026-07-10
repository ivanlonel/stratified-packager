"""
Tests for :mod:`stratified_packager.toolbelt.utils`.

These helpers are pure standard-library functions with no QGIS dependency, so the whole
module runs without a QGIS installation:

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/stratified_packager/toolbelt/test_utils.py
"""

from __future__ import annotations

import re
import sys
import sysconfig
import unicodedata
from typing import TYPE_CHECKING

import hypothesis
import pytest
from hypothesis import strategies as st

from stratified_packager.toolbelt.utils import (
    _MAX_FILENAME_LENGTH,
    _WINDOWS_RESERVED_NAMES,
    coerce_bool,
    python_executable,
    remove_diacritical_marks,
    remove_tree,
    sanitize_filename,
    sanitize_identifier_name,
)

from ._unicode_blocks import UNICODE_BLOCKS

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# coerce_bool
# ---------------------------------------------------------------------------


class TestCoerceBool:
    """Tests for :func:`coerce_bool`."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (True, True),
            (False, False),
            (1, True),
            (0, False),
            (2, True),
            (1.5, True),
            (0.0, False),
            ("true", True),
            ("1", True),
            ("yes", True),
            ("on", True),
            ("t", True),
            ("y", True),
            ("  TRUE  ", True),
            ("Yes", True),
            ("false", False),
            ("0", False),
            ("no", False),
            ("off", False),
            ("f", False),
            ("n", False),
            ("", False),
            ("   ", False),
            ("OFF", False),
        ],
        ids=[
            "bool-true",
            "bool-false",
            "int-1",
            "int-0",
            "int-2",
            "float-truthy",
            "float-zero",
            "str-true",
            "str-1",
            "str-yes",
            "str-on",
            "str-t",
            "str-y",
            "str-padded-upper-true",
            "str-mixedcase-yes",
            "str-false",
            "str-0",
            "str-no",
            "str-off",
            "str-f",
            "str-n",
            "str-empty",
            "str-blank",
            "str-upper-off",
        ],
    )
    def test_recognized_values(self, raw: object, expected: bool) -> None:
        """
        Each recognized value must coerce to the expected boolean.

        :param raw: The raw stored value.
        :param expected: The expected boolean result.
        """
        assert coerce_bool(raw) is expected

    @pytest.mark.parametrize(
        "raw",
        [None, "maybe", "2.5", "truthy", "01"],
        ids=["none", "maybe", "decimal-string", "truthy", "zero-one"],
    )
    def test_unrecognized_raises(self, raw: object) -> None:
        """
        An unrecognized token must raise :exc:`ValueError`.

        :param raw: A value that is not a recognizable boolean token.
        """
        with pytest.raises(ValueError, match="is not a boolean"):
            coerce_bool(raw)


# ---------------------------------------------------------------------------
# remove_diacritical_marks
# ---------------------------------------------------------------------------


class TestRemoveDiacriticalMarks:
    """Tests for :func:`remove_diacritical_marks`."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", ""),
            (
                "Mon çer œnologue m'a conseillé de boire ce vin à ½ vers à 18 ℃ maximum",
                "Mon cer œnologue m'a conseille de boire ce vin a ½ vers a 18 ℃ maximum",
            ),
            (UNICODE_BLOCKS["Basic Latin"], UNICODE_BLOCKS["Basic Latin"]),
            (
                UNICODE_BLOCKS["Latin-1 Supplement"],
                "\xa0¡¢£¤¥¦§¨©ª«¬®¯°±²³\xb4µ¶·\xb8¹º»¼½¾¿AAAAAAÆCEEEEIIIIÐNOOOOO\xd7ØUUUUYÞß"
                "aaaaaaæceeeeiiiiðnooooo÷øuuuuyþy",
            ),
            (
                UNICODE_BLOCKS["Latin Extended-A"],
                "AaAaAaCcCcCcCcDdĐđEeEeEeEeEeGgGgGgGgHhĦħIiIiIiIiI\u0131ĲĳJjKkĸLlLlLlĿŀŁł"
                "NnNnNnŉŊŋOoOoOoŒœRrRrRrSsSsSsSsTtTtŦŧUuUuUuUuUuUuWwYyYZzZzZz\u017f",
            ),
            (
                UNICODE_BLOCKS["Latin Extended-B"],
                "ƀƁƂƃ\u0184ƅƆƇƈƉƊƋƌ\u018dƎƏƐƑƒƓƔƕƖƗƘƙƚƛƜƝƞƟOoƢƣƤƥ\u01a6\u01a7ƨƩƪƫƬƭƮUuƱƲƳƴƵƶ"
                "\u01b7Ƹƹƺƻ\u01bc\u01bdƾƿ\u01c0ǁǂ\u01c3ǄǅǆǇǈǉǊǋǌ"
                "AaIiOoUuUuUuUuUuǝAaAaÆæǤǥGgKkOoOo\u01b7ʒjǱǲǳGgǶǷNnAaÆæØøAaAaEeEeIiIiOoOoRrRrUuUu"
                "SsTt\u021cȝHhȠȡ\u0222\u0223ȤȥAaEeOoOoOoOoYyȴȵȶȷȸȹȺȻȼȽȾȿɀ\u0241ɂɃɄɅɆɇɈɉɊɋɌɍɎɏ",
            ),
            (UNICODE_BLOCKS["IPA Extensions"], UNICODE_BLOCKS["IPA Extensions"]),
            (
                UNICODE_BLOCKS["Spacing Modifier Letters"],
                UNICODE_BLOCKS["Spacing Modifier Letters"],
            ),
            (UNICODE_BLOCKS["Phonetic Extensions"], UNICODE_BLOCKS["Phonetic Extensions"]),
            (
                UNICODE_BLOCKS["Phonetic Extensions Supplement"],
                UNICODE_BLOCKS["Phonetic Extensions Supplement"],
            ),
            (
                "".join(f"a{mark}" for mark in UNICODE_BLOCKS["Combining Diacritical Marks"]),
                "a" * len(UNICODE_BLOCKS["Combining Diacritical Marks"]),
            ),
            (
                UNICODE_BLOCKS["Latin Extended Additional"],
                "AaBbBbBbCcDdDdDdDdDdEeEeEeEeEeFfGgHhHhHhHhHhIiIiKkKkKkLlLlLlLlMmMmMmNnNnNnNn"
                "OoOoOoOoPpPpRrRrRrRrSsSsSsSsSsTtTtTtTtUuUuUuUuUuVvVvWwWwWwWwWwXxXxYyZzZzZz"
                "htwyẚ\u017fẜ\u1e9dẞẟAaAaAaAaAaAaAaAaAaAaAaAaEeEeEeEeEeEeEeEeIiIi"
                "OoOoOoOoOoOoOoOoOoOoOoOoUuUuUuUuUuUuUuYyYyYyYyỺỻỼỽỾ\u1eff",
            ),
            (
                UNICODE_BLOCKS["Superscripts and Subscripts"],
                UNICODE_BLOCKS["Superscripts and Subscripts"],
            ),
            (UNICODE_BLOCKS["Currency Symbols"], UNICODE_BLOCKS["Currency Symbols"]),
            (
                UNICODE_BLOCKS["Letterlike Symbols"],
                "℀℁\u2102℃℄℅℆ℇ℈℉ℊℋℌℍℎℏℐℑℒℓ℔\u2115№℗℘\u2119\u211a\u211b\u211c\u211d℞℟"
                "℠℡™℣\u2124℥Ω℧\u2128℩KA\u212c\u212d\u212e\u212f\u2130\u2131Ⅎ\u2133\u2134"
                "ℵℶℷℸ\u2139℺℻ℼℽℾℿ⅀⅁⅂⅃⅄\u2145\u2146\u2147\u2148\u2149⅊⅋⅌⅍ⅎ⅏",
            ),
            (UNICODE_BLOCKS["Number Forms"], UNICODE_BLOCKS["Number Forms"]),
            (UNICODE_BLOCKS["Enclosed Alphanumerics"], UNICODE_BLOCKS["Enclosed Alphanumerics"]),
            (UNICODE_BLOCKS["Latin Extended-C"], "ⱠⱡⱢⱣⱤⱥⱦⱧⱨⱩⱪⱫⱬⱭⱮⱯⱰⱱⱲⱳⱴⱵⱶⱷⱸⱹⱺⱻⱼⱽⱾⱿ"),
        ],
        ids=[
            "empty",
            "french-sentence",
            "ascii",
            "latin-1-supplement",
            "latin-extended-a",
            "latin-extended-b",
            "ipa-extensions",
            "spacing-modifier-letters",
            "combining-diacritical-marks",
            "phonetic-extensions",
            "phonetic-extensions-supplement",
            "latin-extended-additional",
            "superscripts-and-subscripts",
            "currency-symbols",
            "letterlike-symbols",
            "number-forms",
            "enclosed-alphanumerics",
            "latin-extended-c",
        ],
    )
    def test_known_strings(self, text: str, expected: str) -> None:
        """
        Each input must have its combining marks stripped to the expected form.

        :param text: Input string possibly carrying diacritical marks.
        :param expected: The string with diacritical marks removed.
        """
        assert remove_diacritical_marks(text) == expected

    @hypothesis.given(text=st.text())
    def test_result_has_no_nonspacing_marks(self, text: str) -> None:
        """
        No character in the result may belong to the Unicode ``Mn`` category.

        :param text: Arbitrary input string.
        """
        assert all(unicodedata.category(char) != "Mn" for char in remove_diacritical_marks(text))

    @hypothesis.given(text=st.text())
    def test_idempotent(self, text: str) -> None:
        """
        Stripping marks a second time must leave the result unchanged.

        :param text: Arbitrary input string.
        """
        once = remove_diacritical_marks(text)
        assert remove_diacritical_marks(once) == once

    @hypothesis.given(text=st.text(alphabet=st.characters(min_codepoint=0, max_codepoint=127)))
    def test_ascii_is_returned_verbatim(self, text: str) -> None:
        """
        ASCII text carries no combining marks and must be returned unchanged.

        :param text: Arbitrary ASCII-only input string.
        """
        assert remove_diacritical_marks(text) == text


# ---------------------------------------------------------------------------
# sanitize_identifier_name
# ---------------------------------------------------------------------------


class TestSanitizeIdentifierName:
    """Tests for :func:`sanitize_identifier_name`."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", ""),
            (
                "_0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
                "_0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
            ),
            ("a---b...c", "a_b_c"),
            ("Hello, World!", "Hello_World_"),
            ("_", "_"),
            ("!\"#$%&'()*+,-./ :;<=>?@\t[\\]^_`{|}~", "___"),
            ("1", "_1"),
            ("100%", "_100_"),
            (
                "Mon çer œnologue m'a conseillé de boire ce vin à ½ vers à 18 ℃ maximum",
                "Mon_cer_nologue_m_a_conseille_de_boire_ce_vin_a_vers_a_18_maximum",
            ),
            (
                UNICODE_BLOCKS["Basic Latin"],
                "_0123456789_ABCDEFGHIJKLMNOPQRSTUVWXYZ___abcdefghijklmnopqrstuvwxyz_",
            ),
            (
                UNICODE_BLOCKS["Latin-1 Supplement"],
                "_AAAAAA_CEEEEIIII_NOOOOO_UUUUY_aaaaaa_ceeeeiiii_nooooo_uuuuy_y",
            ),
            (
                UNICODE_BLOCKS["Latin Extended-A"],
                "AaAaAaCcCcCcCcDd_EeEeEeEeEeGgGgGgGgHh_IiIiIiIiI_JjKk_LlLlLl_NnNnNn_OoOoOo"
                "_RrRrRrSsSsSsSsTtTt_UuUuUuUuUuUuWwYyYZzZzZz_",
            ),
            (
                UNICODE_BLOCKS["Latin Extended-B"],
                "_Oo_Uu_AaIiOoUuUuUuUuUu_AaAa_GgKkOoOo_j_Gg_NnAa_AaAaEeEeIiIiOoOoRrRrUuUuSsTt"
                "_Hh_AaEeOoOoOoOoYy_",
            ),
            (UNICODE_BLOCKS["IPA Extensions"], "_"),
            (UNICODE_BLOCKS["Spacing Modifier Letters"], "_"),
            (
                "".join(f"a{mark}" for mark in UNICODE_BLOCKS["Combining Diacritical Marks"]),
                "a" * len(UNICODE_BLOCKS["Combining Diacritical Marks"]),
            ),
            (UNICODE_BLOCKS["Phonetic Extensions"], "_"),
            (UNICODE_BLOCKS["Phonetic Extensions Supplement"], "_"),
            (
                UNICODE_BLOCKS["Latin Extended Additional"],
                "AaBbBbBbCcDdDdDdDdDdEeEeEeEeEeFfGgHhHhHhHhHhIiIiKkKkKkLlLlLlLlMmMmMm"
                "NnNnNnNnOoOoOoOoPpPpRrRrRrRrSsSsSsSsSsTtTtTtTtUuUuUuUuUuVvVvWwWwWwWwWw"
                "XxXxYyZzZzZzhtwy_AaAaAaAaAaAaAaAaAaAaAaAaEeEeEeEeEeEeEeEeIiIi"
                "OoOoOoOoOoOoOoOoOoOoOoOoUuUuUuUuUuUuUuYyYyYyYy_",
            ),
            (UNICODE_BLOCKS["Superscripts and Subscripts"], "_"),
            (UNICODE_BLOCKS["Currency Symbols"], "_"),
            (UNICODE_BLOCKS["Letterlike Symbols"], "_KA_"),
            (UNICODE_BLOCKS["Number Forms"], "_"),
            (UNICODE_BLOCKS["Enclosed Alphanumerics"], "_"),
            (UNICODE_BLOCKS["Latin Extended-C"], "_"),
            (UNICODE_BLOCKS["CJK Compatibility"], "_"),
            (UNICODE_BLOCKS["Latin Extended-D"], "_"),
            (UNICODE_BLOCKS["Latin Extended-E"], "_"),
            (UNICODE_BLOCKS["Alphabetic Presentation Forms"], "_"),
            (UNICODE_BLOCKS["Halfwidth and Fullwidth Forms"], "_"),
            (UNICODE_BLOCKS["Latin Extended-F"], "_"),
            (UNICODE_BLOCKS["Mathematical Alphanumeric Symbols"], "_"),
            (UNICODE_BLOCKS["Latin Extended-G"], "_"),
            (UNICODE_BLOCKS["Enclosed Alphanumeric Supplement"], "_"),
        ],
        ids=[
            "empty",
            "already-valid",
            "runs-collapse",
            "punctuation",
            "lone-underscore",
            "underscore-between-symbols",
            "lone-digit",
            "leading-digit-and-symbol",
            "french-sentence",
            "ascii",
            "latin-1-supplement",
            "latin-extended-a",
            "latin-extended-b",
            "ipa-extensions",
            "spacing-modifier-letters",
            "combining-diacritical-marks",
            "phonetic-extensions",
            "phonetic-extensions-supplement",
            "latin-extended-additional",
            "superscripts-and-subscripts",
            "currency-symbols",
            "letterlike-symbols",
            "number-forms",
            "enclosed-alphanumerics",
            "latin-extended-c",
            "cjk-compatibility",
            "latin-extended-d",
            "latin-extended-e",
            "alphabetic-presentation-forms",
            "halfwidth-and-fullwidth-forms",
            "latin-extended-f",
            "mathematical-alphanumeric-symbols",
            "latin-extended-g",
            "enclosed-alphanumeric-supplement",
        ],
    )
    def test_known_strings(self, text: str, expected: str) -> None:
        """
        Each input must be turned into the expected identifier-safe string.

        :param text: Input string to sanitize.
        :param expected: The expected identifier-safe result.
        """
        assert sanitize_identifier_name(text) == expected

    @hypothesis.given(text=st.text())
    def test_result_has_no_non_word_characters(self, text: str) -> None:
        """
        Every run of non-word characters is collapsed, so the result has only word characters.

        :param text: Arbitrary input string.
        """
        assert re.search(r"[^_0-9A-Za-z]", sanitize_identifier_name(text)) is None

    @hypothesis.given(text=st.text())
    def test_result_never_starts_with_a_digit(self, text: str) -> None:
        """
        A leading decimal digit must be prefixed with ``_`` so the result is a valid start.

        :param text: Arbitrary input string.
        """
        assert re.match(r"\d", sanitize_identifier_name(text)) is None

    @hypothesis.given(text=st.text())
    def test_idempotent(self, text: str) -> None:
        """
        Sanitizing an already-sanitized name must leave it unchanged.

        :param text: Arbitrary input string.
        """
        once = sanitize_identifier_name(text)
        assert sanitize_identifier_name(once) == once


# ---------------------------------------------------------------------------
# sanitize_filename
# ---------------------------------------------------------------------------


class TestSanitizeFilename:
    """Tests for :func:`sanitize_filename`."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("", "_"),
            (
                "_0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvw.xyz",
                "_0123456789-ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvw.xyz",
            ),
            ("a/b\\c", "abc"),
            ('a<b>c:d"e|f?g*h', "abcdefgh"),
            ("  spaced \t  name  ", "spaced name"),
            ("name.", "name"),
            ("name . ", "name"),
            ("a\x00b\x1f\x7fc", "abc"),
            ("CON", "_CON"),
            ("con.txt", "_con.txt"),
            ("Nul.tar.gz", "_Nul.tar.gz"),
            ("LPT5", "_LPT5"),
            ("CONSOLE", "CONSOLE"),
            ("Ação São Paulo — região nº 1", "Ação São Paulo — região nº 1"),
            ("<full>", "full"),
            ("...", "_"),
            ("a" * (_MAX_FILENAME_LENGTH * 2), "a" * _MAX_FILENAME_LENGTH),
        ],
        ids=[
            "empty",
            "already-valid",
            "path-separators",
            "illegal-characters",
            "whitespace-collapse",
            "trailing-dot",
            "trailing-dot-space",
            "control-characters",
            "reserved-bare",
            "reserved-with-extension",
            "reserved-double-extension",
            "reserved-lpt",
            "reserved-prefix-only",
            "unicode-preserved",
            "angle-brackets-stripped",
            "only-dots",
            "overlong-truncated",
        ],
    )
    def test_known_strings(self, text: str, expected: str) -> None:
        """
        Each input must be turned into the expected filename-safe string.

        :param text: Input string to sanitize.
        :param expected: The expected filename-safe result.
        """
        assert sanitize_filename(text) == expected

    @hypothesis.given(text=st.text())
    def test_result_has_no_illegal_characters(self, text: str) -> None:
        """
        The result may contain no path separator, Windows-illegal or control character.

        :param text: Arbitrary input string.
        """
        assert re.search(r'[\x00-\x1f\x7f<>:"/\\|?*]', sanitize_filename(text)) is None

    @hypothesis.given(text=st.text())
    def test_result_is_never_empty(self, text: str) -> None:
        """
        The result is never empty; ``_`` stands in when nothing survives sanitization.

        :param text: Arbitrary input string.
        """
        assert sanitize_filename(text)

    @hypothesis.given(text=st.text())
    def test_result_has_no_leading_or_trailing_space_nor_trailing_dot(self, text: str) -> None:
        """
        Windows rejects names ending in dots or spaces; leading spaces are trimmed too.

        :param text: Arbitrary input string.
        """
        result = sanitize_filename(text)
        assert result == result.strip(" ")
        assert not result.endswith(".")

    @hypothesis.given(text=st.text())
    def test_result_is_not_a_reserved_device_name(self, text: str) -> None:
        """
        The base name before the first dot must never be a reserved Windows device name.

        :param text: Arbitrary input string.
        """
        result = sanitize_filename(text)
        assert result.partition(".")[0].rstrip(" ").upper() not in _WINDOWS_RESERVED_NAMES

    @hypothesis.given(text=st.text())
    def test_result_fits_the_component_length_limit(self, text: str) -> None:
        """
        The result must fit the per-component filesystem length limit.

        :param text: Arbitrary input string.
        """
        assert len(sanitize_filename(text)) <= _MAX_FILENAME_LENGTH

    @hypothesis.given(text=st.text())
    def test_idempotent(self, text: str) -> None:
        """
        Sanitizing an already-sanitized name must leave it unchanged.

        :param text: Arbitrary input string.
        """
        once = sanitize_filename(text)
        assert sanitize_filename(once) == once


# ---------------------------------------------------------------------------
# python_executable
# ---------------------------------------------------------------------------


class TestPythonExecutable:
    """Tests for :func:`python_executable`."""

    def test_returns_sys_executable_when_already_python(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        When ``sys.executable`` is itself a Python interpreter it is returned unchanged.

        :param monkeypatch: Fixture used to point ``sys.executable`` at a fake interpreter.
        :param tmp_path: Temporary directory holding the fake interpreter.
        """
        exe = tmp_path / "python3.12"
        exe.write_text("")
        monkeypatch.setattr(sys, "executable", str(exe))
        assert python_executable() == exe

    def test_windows_embedded_uses_prefix_python_exe(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        On Windows the interpreter is located as ``<exec_prefix>/python.exe``.

        :param monkeypatch: Fixture used to simulate an embedded Windows interpreter.
        :param tmp_path: Temporary directory standing in for the interpreter prefix.
        """
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(sys, "executable", str(tmp_path / "qgis-bin.exe"))
        monkeypatch.setattr(sys, "_base_executable", str(tmp_path / "qgis-bin.exe"))
        monkeypatch.setattr(sys, "exec_prefix", str(tmp_path))
        monkeypatch.setattr(sys, "base_exec_prefix", str(tmp_path))
        python = tmp_path / "python.exe"
        python.write_text("")
        assert python_executable() == python

    def test_posix_embedded_uses_bindir_versioned_python(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        On POSIX the interpreter is located in ``BINDIR`` as ``pythonX.Y``.

        :param monkeypatch: Fixture used to simulate an embedded POSIX interpreter.
        :param tmp_path: Temporary directory standing in for the interpreter prefix.
        """
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(sys, "executable", str(tmp_path / "qgis"))
        monkeypatch.setattr(sys, "_base_executable", str(tmp_path / "qgis"))
        bindir = tmp_path / "bin"
        bindir.mkdir()
        python = bindir / f"python{sys.version_info.major}.{sys.version_info.minor}"
        python.write_text("")
        monkeypatch.setattr(sysconfig, "get_config_var", lambda _name: str(bindir))
        assert python_executable() == python

    def test_returns_none_when_not_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """
        When no interpreter can be located the result is :data:`None`.

        :param monkeypatch: Fixture used to simulate an embedded interpreter with no Python.
        :param tmp_path: Temporary directory whose ``BINDIR`` holds no interpreter.
        """
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(sys, "executable", str(tmp_path / "qgis"))
        monkeypatch.setattr(sys, "_base_executable", None)
        monkeypatch.setattr(sysconfig, "get_config_var", lambda _name: str(tmp_path / "empty"))
        assert python_executable() is None


# ---------------------------------------------------------------------------
# remove_tree
# ---------------------------------------------------------------------------


class TestRemoveTree:
    """Tests for :func:`remove_tree`."""

    def test_removes_nested_tree(self, tmp_path: Path) -> None:
        """
        A populated directory tree is removed and success is reported.

        :param tmp_path: Temporary directory hosting the tree.
        """
        tree = tmp_path / "workdir"
        (tree / "staging").mkdir(parents=True)
        (tree / "staging/layer.gpkg").write_bytes(b"data")
        (tree / "template.gpkg").write_bytes(b"data")
        assert remove_tree(tree, attempts=1)
        assert not tree.exists()

    def test_missing_path_is_success(self, tmp_path: Path) -> None:
        """
        A path that does not exist counts as already removed.

        :param tmp_path: Temporary directory whose child never existed.
        """
        assert remove_tree(tmp_path / "never_created", attempts=1)

    @pytest.mark.skipif(
        sys.platform != "win32", reason="POSIX allows deleting files that are held open"
    )
    def test_reports_residue_when_a_file_is_locked(self, tmp_path: Path) -> None:
        """
        On Windows an open file survives removal and the failure is reported, not raised.

        :param tmp_path: Temporary directory hosting the tree.
        """
        tree = tmp_path / "workdir"
        tree.mkdir()
        locked = tree / "locked.gpkg"
        with locked.open("w", encoding="utf-8"):
            assert not remove_tree(tree, attempts=2, delay=0.01)
            assert locked.exists()
        assert remove_tree(tree, attempts=1)
