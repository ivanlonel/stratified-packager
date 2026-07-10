"""
Tests for :mod:`stratified_packager.toolbelt.zipping`.

Pure standard-library helpers with no QGIS dependency, so the whole module runs
without a QGIS installation:

.. code-block:: bash

    pytest -p no:pytest_qgis -p no:pytest-qt tests/stratified_packager/toolbelt/test_zipping.py
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

import hashlib
import re
import zipfile
from typing import TYPE_CHECKING

import hypothesis
import pytest
from hypothesis import strategies as st

from stratified_packager.toolbelt.zipping import (
    OperationAbortedError,
    build_zip,
    case_insensitive_collisions,
    filename_component_error,
    iter_file_members,
    publish_atomic,
    remove_stale_parts,
    sha256_sidecar,
    split_archive_path,
)

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# filename_component_error / split_archive_path
# ---------------------------------------------------------------------------


class TestFilenameComponentError:
    """Tests for :func:`filename_component_error`."""

    @pytest.mark.parametrize(
        "component",
        ["plain", "with space", "dotted.name", "Ação nº 1", "_CON", "CONSOLE", ".hidden"],
        ids=["plain", "space", "dotted", "unicode", "reserved-prefixed", "longer", "hidden"],
    )
    def test_valid_components(self, component: str) -> None:
        """
        Valid components must yield no violation.

        :param component: A component expected to pass.
        """
        assert filename_component_error(component) is None

    @pytest.mark.parametrize(
        ("component", "fragment"),
        [
            ("", "empty or a relative"),
            (".", "empty or a relative"),
            ("..", "empty or a relative"),
            ("a/b", "illegal character"),
            ("a\\b", "illegal character"),
            ("a:b", "illegal character"),
            ("a\x07b", "illegal character"),
            ("name.", "trailing dot"),
            (" name", "spaces"),
            ("name ", "spaces"),
            ("CON", "reserved"),
            ("nul.txt", "reserved"),
            ("a" * 256, "exceeds"),
        ],
        ids=[
            "empty",
            "dot",
            "dotdot",
            "slash",
            "backslash",
            "colon",
            "control",
            "trailing-dot",
            "leading-space",
            "trailing-space",
            "reserved",
            "reserved-extension",
            "overlong",
        ],
    )
    def test_invalid_components(self, component: str, fragment: str) -> None:
        """
        Invalid components must yield a violation mentioning the expected reason.

        :param component: A component expected to fail.
        :param fragment: Substring expected in the violation message.
        """
        error = filename_component_error(component)
        assert error is not None
        assert fragment in error


class TestSplitArchivePath:
    """Tests for :func:`split_archive_path`."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("file", ("file",)),
            ("dir/file", ("dir", "file")),
            ("dir\\file", ("dir", "file")),
            ("a/b/c.gpkg", ("a", "b", "c.gpkg")),
        ],
        ids=["bare", "posix-sep", "windows-sep", "nested"],
    )
    def test_valid_paths(self, path: str, expected: tuple[str, ...]) -> None:
        """
        Valid relative paths split into their components.

        :param path: The relative path to validate.
        :param expected: The expected components.
        """
        assert split_archive_path(path) == expected

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "  ",
            "/abs",
            "\\abs",
            "C:\\abs",
            "C:rel",
            "\\\\server\\share",
            "../escape",
            "a/../b",
            "a/./b",
            "a//b",
            "dir/CON",
            "dir/name.",
            "a/b ",
        ],
        ids=[
            "empty",
            "blank",
            "posix-absolute",
            "backslash-absolute",
            "drive-absolute",
            "drive-relative",
            "unc",
            "leading-dotdot",
            "inner-dotdot",
            "inner-dot",
            "empty-component",
            "reserved-component",
            "trailing-dot-component",
            "trailing-space-component",
        ],
    )
    def test_invalid_paths(self, path: str) -> None:
        """
        Absolute, escaping or component-invalid paths raise :exc:`ValueError`.

        :param path: The path expected to be rejected.
        """
        with pytest.raises(ValueError, match="invalid archive path"):
            split_archive_path(path)

    @hypothesis.given(
        components=st.lists(
            st.text(
                alphabet=st.characters(categories=("L", "N"), include_characters="_- "),
                min_size=1,
                max_size=20,
            ).map(lambda s: f"x{s.strip(' ')}"),
            min_size=1,
            max_size=4,
        )
    )
    def test_well_formed_paths_round_trip(self, components: list[str]) -> None:
        """
        Paths joined from letter/digit components always validate back to them.

        :param components: Generated safe components.
        """
        assert split_archive_path("/".join(components)) == tuple(components)

    @hypothesis.given(path=st.text(max_size=60))
    def test_never_silently_sanitizes(self, path: str) -> None:
        """
        The validator either returns the exact components or raises — never rewrites.

        :param path: Arbitrary candidate path.
        """
        try:
            components = split_archive_path(path)
        except ValueError:
            return
        assert "/".join(components) == re.sub(r"[\\/]", "/", path)


class TestCaseInsensitiveCollisions:
    """Tests for :func:`case_insensitive_collisions`."""

    def test_detects_collisions_and_ignores_exact_duplicates(self) -> None:
        """Distinct spellings folding to one key collide; exact duplicates do not."""
        groups = case_insensitive_collisions(["a/B.gpkg", "A/b.gpkg", "a/B.gpkg", "c"])
        assert groups == [["A/b.gpkg", "a/B.gpkg"]]

    def test_no_collisions(self) -> None:
        """Unique paths produce no groups."""
        assert case_insensitive_collisions(["a", "b", "c/d"]) == []

    @hypothesis.given(paths=st.lists(st.text(max_size=15), max_size=10))
    def test_groups_always_hold_multiple_distinct_spellings(self, paths: list[str]) -> None:
        """
        Every reported group has at least two distinct spellings sharing one casefold.

        :param paths: Arbitrary path list.
        """
        for group in case_insensitive_collisions(paths):
            assert len(group) > 1
            assert len({p.casefold() for p in group}) == 1


# ---------------------------------------------------------------------------
# Zip assembly & publishing
# ---------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Build a small source tree with a compressible payload."""
    root = tmp_path / "tree"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_text("alpha " * 1000, encoding="utf-8")
    (root / "sub/b.bin").write_bytes(b"\x00" * 4096)
    return root


class TestIterFileMembers:
    """Tests for :func:`iter_file_members`."""

    def test_yields_sorted_files_with_prefix(self, tree: Path) -> None:
        """
        Files are yielded with slash-separated arcnames under the given prefix.

        :param tree: Source tree fixture.
        """
        members = list(iter_file_members(tree, "extra"))
        assert [(m[0].name, m[1]) for m in members] == [
            ("a.txt", "extra/a.txt"),
            ("b.bin", "extra/sub/b.bin"),
        ]

    def test_no_prefix(self, tree: Path) -> None:
        """
        Without a prefix the arcnames are the tree-relative paths.

        :param tree: Source tree fixture.
        """
        assert [m[1] for m in iter_file_members(tree)] == ["a.txt", "sub/b.bin"]


class TestBuildZip:
    """Tests for :func:`build_zip`."""

    def test_round_trips_content(self, tree: Path, tmp_path: Path) -> None:
        """
        Members are stored under their arcnames with identical content.

        :param tree: Source tree fixture.
        :param tmp_path: Destination directory.
        """
        out = build_zip(tmp_path / "out.zip", iter_file_members(tree), compression_level=6)
        with zipfile.ZipFile(out) as zf:
            assert sorted(zf.namelist()) == ["a.txt", "sub/b.bin"]
            assert zf.read("a.txt") == (tree / "a.txt").read_bytes()
            assert zf.read("sub/b.bin") == (tree / "sub/b.bin").read_bytes()

    def test_level_zero_stores_uncompressed(self, tree: Path, tmp_path: Path) -> None:
        """
        Level 0 selects ``ZIP_STORED`` for every member.

        :param tree: Source tree fixture.
        :param tmp_path: Destination directory.
        """
        out = build_zip(tmp_path / "out.zip", iter_file_members(tree), compression_level=0)
        with zipfile.ZipFile(out) as zf:
            assert {i.compress_type for i in zf.infolist()} == {zipfile.ZIP_STORED}

    def test_deflate_compresses(self, tree: Path, tmp_path: Path) -> None:
        """
        A compressible member must come out Deflate-compressed and smaller.

        :param tree: Source tree fixture.
        :param tmp_path: Destination directory.
        """
        out = build_zip(tmp_path / "out.zip", iter_file_members(tree), compression_level=9)
        with zipfile.ZipFile(out) as zf:
            info = zf.getinfo("a.txt")
            assert info.compress_type == zipfile.ZIP_DEFLATED
            assert info.compress_size < info.file_size

    def test_abort_removes_partial_zip(self, tree: Path, tmp_path: Path) -> None:
        """
        An abort raises :exc:`OperationAbortedError` and removes the partial file.

        :param tree: Source tree fixture.
        :param tmp_path: Destination directory.
        """
        out = tmp_path / "out.zip"
        with pytest.raises(OperationAbortedError):
            build_zip(out, iter_file_members(tree), compression_level=6, abort=lambda: True)
        assert not out.exists()


class TestPublishAtomic:
    """Tests for :func:`publish_atomic`."""

    def test_publishes_and_cleans_part(self, tmp_path: Path) -> None:
        """
        The destination appears with identical content and no ``.part`` remains.

        :param tmp_path: Working directory.
        """
        built = tmp_path / "built.zip"
        built.write_bytes(b"payload")
        final = tmp_path / "out/published.zip"
        assert publish_atomic(built, final) == final
        assert final.read_bytes() == b"payload"
        assert not final.with_name(final.name + ".part").exists()

    def test_abort_removes_part_and_final_never_appears(self, tmp_path: Path) -> None:
        """
        An aborted publish leaves neither the ``.part`` nor the final file.

        :param tmp_path: Working directory.
        """
        built = tmp_path / "built.zip"
        built.write_bytes(b"x" * (1 << 23))
        final = tmp_path / "out/published.zip"
        with pytest.raises(OperationAbortedError):
            publish_atomic(built, final, abort=lambda: True)
        assert not final.exists()
        assert not final.with_name(final.name + ".part").exists()


class TestChecksumAndStaleParts:
    """Tests for :func:`sha256_sidecar` and :func:`remove_stale_parts`."""

    def test_sidecar_matches_hashlib(self, tmp_path: Path) -> None:
        """
        The sidecar carries the sha256sum-format digest of the file.

        :param tmp_path: Working directory.
        """
        target = tmp_path / "data.zip"
        target.write_bytes(b"abc123")
        sidecar = sha256_sidecar(target)
        digest = hashlib.sha256(b"abc123").hexdigest()
        assert sidecar.name == "data.zip.sha256"
        assert sidecar.read_text(encoding="ascii") == f"{digest}  data.zip\n"

    def test_sidecar_handles_non_ascii_filename(self, tmp_path: Path) -> None:
        """
        A diacritical zip name (e.g. an accented stratum) is written UTF-8, not ASCII.

        :param tmp_path: Working directory.
        """
        target = tmp_path / "SÃO JOSÉ.zip"
        target.write_bytes(b"xyz")
        sidecar = sha256_sidecar(target)  # must not raise UnicodeEncodeError
        digest = hashlib.sha256(b"xyz").hexdigest()
        assert sidecar.read_text(encoding="utf-8") == f"{digest}  SÃO JOSÉ.zip\n"

    def test_removes_only_named_parts(self, tmp_path: Path) -> None:
        """
        Only ``.part`` files for the given zip names are removed.

        :param tmp_path: Working directory.
        """
        ours = tmp_path / "north.zip.part"
        ours.write_bytes(b"")
        foreign = tmp_path / "other.zip.part"
        foreign.write_bytes(b"")
        removed = remove_stale_parts(tmp_path, ["north.zip", "missing.zip"])
        assert removed == [ours]
        assert not ours.exists()
        assert foreign.exists()
