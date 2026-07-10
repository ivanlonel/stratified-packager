"""
Test suite for :mod:`stratified_packager.toolbelt.mapping_proxy`.

The module under test touches no QGIS objects (the conversion registry, the
:class:`~stratified_packager.toolbelt.mapping_proxy.MappingProxy` base, and the
:class:`~stratified_packager.toolbelt.mapping_proxy.EnvironmentVariables` proxy are all
pure-Python), so these tests require neither a QGIS runtime nor ``pytest-qgis``: there is
no :func:`pytest.importorskip` guard and no module-level :data:`pytestmark`. The environment
tests use injected mappings, so they touch no real process environment except the one
:func:`monkeypatch`-guarded check that the default backing is :data:`os.environ`.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import hypothesis
import pytest
from hypothesis import strategies as st

import stratified_packager.toolbelt.mapping_proxy as mapping_proxy_module
from stratified_packager.toolbelt.mapping_proxy import (
    BoolEnvVar,
    EnvironmentVariables,
    FloatEnvVar,
    IntEnvVar,
    PathEnvVar,
    StrEnvVar,
    TypeConverter,
    from_storage,
    register_converter,
    to_storage,
)

from ._conversion_samples import PURE_PROPERTY, Perm, Speed

if TYPE_CHECKING:
    from collections.abc import Generator


class _ExampleEnv(EnvironmentVariables):
    """Disposable env schema exercising the scalar :class:`EnvVar` descriptors."""

    FLAG = BoolEnvVar(default=False)
    COUNT = IntEnvVar(default=3)
    RATIO = FloatEnvVar(default=1.5)
    LABEL = StrEnvVar(default="def", key="CUSTOM_LABEL")
    ROOT = PathEnvVar(default=Path("base"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def restore_converters() -> Generator[None, None, None]:
    """
    Restore the converter registry after a test mutates it.

    :return: Nothing; yields control to the test body.
    """
    snapshot = dict(mapping_proxy_module._CONVERTERS)  # registry is module-private
    yield
    mapping_proxy_module._CONVERTERS.clear()  # restore after a mutating test
    mapping_proxy_module._CONVERTERS.update(snapshot)


# ---------------------------------------------------------------------------
# __all__ completeness
# ---------------------------------------------------------------------------


def test_all_symbols_are_importable() -> None:
    """Every name in ``__all__`` must be importable from the module."""
    for name in mapping_proxy_module.__all__:
        assert hasattr(mapping_proxy_module, name), f"__all__ lists {name!r} but it is missing."


# ---------------------------------------------------------------------------
# Conversion registry
# ---------------------------------------------------------------------------


class TestConversion:
    """Tests for :func:`to_storage`, :func:`from_storage`, and the registry."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("text", "text"),
            (7, 7),
            (2.5, 2.5),
            (True, True),
            (["a", "b"], ["a", "b"]),
        ],
        ids=["str", "int", "float", "bool", "list"],
    )
    def test_to_storage_native_passthrough(self, value: object, expected: object) -> None:
        """
        Native types must serialize to an equal storable value.

        :param value: The Python value to serialize.
        :param expected: The expected stored representation.
        """
        assert to_storage(value) == expected

    def test_to_storage_path_uses_base_converter(self) -> None:
        """
        A concrete :class:`pathlib.Path` instance must resolve the :class:`pathlib.Path`
        converter via MRO.
        """
        path = Path("a") / "b"
        assert to_storage(path) == str(path)

    def test_to_storage_enum_reduces_to_value(self) -> None:
        """An :class:`enum.Enum` member must serialize to its ``value``."""
        assert to_storage(Speed.FAST) == Speed.FAST.value

    def test_to_storage_datetime_isoformat(self) -> None:
        """A :class:`~datetime.datetime` must serialize to its ISO string."""
        moment = datetime(2026, 5, 28, 9, 30)  # noqa: DTZ001  # naive is fine for serialization
        assert to_storage(moment) == moment.isoformat()

    def test_to_storage_unregistered_returns_unchanged(self) -> None:
        """A value whose type has no converter must be returned unchanged."""
        sentinel = object()
        assert to_storage(sentinel) is sentinel

    @pytest.mark.parametrize(
        ("raw", "target", "expected"),
        [
            ("5", int, 5),
            (5.9, int, 5),
            ("2.5", float, 2.5),
            ("true", bool, True),
            ("off", bool, False),
            (1, bool, True),
            (7, str, "7"),
        ],
        ids=["int_str", "int_float", "float", "bool_true", "bool_off", "bool_int", "str"],
    )
    def test_from_storage_coercions(self, raw: object, target: type, expected: object) -> None:
        """
        Stored values must be coerced to the requested type.

        :param raw: The stored value.
        :param target: The requested Python type.
        :param expected: The expected coerced value.
        """
        assert from_storage(raw, target) == expected

    def test_from_storage_path_roundtrip(self) -> None:
        """A stored path string must rebuild an equal :class:`~pathlib.Path`."""
        path = Path("c") / "d"
        assert from_storage(str(path), Path) == path

    def test_from_storage_datetime_roundtrip(self) -> None:
        """A stored ISO string must rebuild an equal :class:`~datetime.datetime`."""
        moment = datetime(2026, 1, 2, 3, 4, 5)  # noqa: DTZ001  # naive is fine for serialization
        assert from_storage(moment.isoformat(), datetime) == moment

    def test_from_storage_date_roundtrip(self) -> None:
        """A stored ISO string must rebuild an equal :class:`~datetime.date`."""
        assert from_storage("2026-05-28", date) == date(2026, 5, 28)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (["a", "b"], ["a", "b"]),
            (("a", "b"), ["a", "b"]),
            (frozenset({"solo"}), ["solo"]),
            (range(3), ["0", "1", "2"]),
        ],
        ids=["list", "tuple", "frozenset", "range"],
    )
    def test_from_storage_list_accepts_any_iterable(
        self, raw: object, expected: list[str]
    ) -> None:
        """
        A :class:`~builtins.list` cast must stringify the items of any non-string iterable.

        :param raw: The stored iterable value.
        :param expected: The expected list of stringified items.
        """
        assert from_storage(raw, list) == expected

    def test_from_storage_list_keeps_string_whole(self) -> None:
        """A :class:`~builtins.list` cast must wrap a string, not explode it into characters."""
        assert from_storage("abc", list) == ["abc"]

    def test_from_storage_enum_by_value(self) -> None:
        """An :class:`enum.Enum` target must be reconstructed by value lookup."""
        assert from_storage(2, Speed) is Speed.FAST

    def test_from_storage_intflag_combination(self) -> None:
        """An :class:`enum.IntFlag` target must rebuild a combined value."""
        combined = (Perm.READ | Perm.WRITE).value
        assert from_storage(combined, Perm) == (Perm.READ | Perm.WRITE)

    def test_from_storage_unregistered_raises(self) -> None:
        """A target type with no converter must raise :exc:`TypeError`."""
        with pytest.raises(TypeError, match="No converter registered"):
            from_storage("x", complex)

    @pytest.mark.usefixtures("restore_converters")
    def test_register_converter_roundtrip(self) -> None:
        """A freshly registered converter must drive :func:`to_storage`/:func:`from_storage`."""
        register_converter(bytes, lambda b: b.decode(), lambda r: str(r).encode())
        assert to_storage(b"hi") == "hi"
        assert from_storage("hi", bytes) == b"hi"


class TestConversionProperties:
    """Property-based round-trip checks for the converter registry."""

    @PURE_PROPERTY
    @hypothesis.given(value=st.booleans())
    def test_bool_roundtrip(self, value: bool) -> None:
        """
        A boolean must survive a serialize/deserialize round-trip.

        :param value: The boolean to round-trip.
        """
        assert from_storage(to_storage(value), bool) is value

    @PURE_PROPERTY
    @hypothesis.given(value=st.integers())
    def test_int_roundtrip(self, value: int) -> None:
        """
        An integer must round-trip unchanged.

        :param value: The integer to round-trip.
        """
        assert from_storage(to_storage(value), int) == value

    @PURE_PROPERTY
    @hypothesis.given(value=st.floats(allow_nan=False))
    def test_float_roundtrip(self, value: float) -> None:
        """
        A non-NaN float must round-trip unchanged.

        :param value: The float to round-trip.
        """
        assert from_storage(to_storage(value), float) == value

    @PURE_PROPERTY
    @hypothesis.given(value=st.text())
    def test_str_roundtrip(self, value: str) -> None:
        """
        An arbitrary string must round-trip unchanged.

        :param value: The string to round-trip.
        """
        assert from_storage(to_storage(value), str) == value

    @PURE_PROPERTY
    @hypothesis.given(value=st.lists(st.text()))
    def test_str_list_roundtrip(self, value: list[str]) -> None:
        """
        A list of strings must round-trip unchanged.

        :param value: The list of strings to round-trip.
        """
        assert from_storage(to_storage(value), list) == value

    @PURE_PROPERTY
    @hypothesis.given(
        parts=st.lists(st.from_regex(r"[A-Za-z0-9_.-]+", fullmatch=True), min_size=1, max_size=4)
    )
    def test_path_roundtrip(self, parts: list[str]) -> None:
        """
        A filesystem path must round-trip via its string form.

        :param parts: Path segments composed into a relative path.
        """
        path = Path(*parts)
        assert from_storage(to_storage(path), Path) == path

    @PURE_PROPERTY
    @hypothesis.given(value=st.datetimes())
    def test_datetime_roundtrip(self, value: datetime) -> None:
        """
        A datetime must round-trip via its ISO-8601 form.

        :param value: The datetime to round-trip.
        """
        assert from_storage(to_storage(value), datetime) == value

    @PURE_PROPERTY
    @hypothesis.given(value=st.dates())
    def test_date_roundtrip(self, value: date) -> None:
        """
        A date must round-trip via its ISO-8601 form.

        :param value: The date to round-trip.
        """
        assert from_storage(to_storage(value), date) == value

    @PURE_PROPERTY
    @hypothesis.given(value=st.sampled_from(list(Speed)))
    def test_enum_roundtrip(self, value: Speed) -> None:
        """
        An enum member must round-trip via its value.

        :param value: The enum member to round-trip.
        """
        assert from_storage(to_storage(value), Speed) is value

    @PURE_PROPERTY
    @hypothesis.given(value=st.builds(Perm, st.integers(min_value=0, max_value=3)))
    def test_intflag_roundtrip(self, value: Perm) -> None:
        """
        Any flag combination must round-trip via its value.

        :param value: The flag combination to round-trip.
        """
        assert from_storage(to_storage(value), Perm) == value

    @PURE_PROPERTY
    @hypothesis.given(items=st.lists(st.integers() | st.text() | st.booleans()))
    def test_to_str_list_stringifies_items(self, items: list[object]) -> None:
        """
        Every item of a non-string iterable must be stringified.

        :param items: Arbitrary mixed-type items.
        """
        assert mapping_proxy_module._to_str_list(items) == [str(item) for item in items]

    @PURE_PROPERTY
    @hypothesis.given(value=st.text())
    def test_to_str_list_keeps_string_whole(self, value: str) -> None:
        """
        A string must never be exploded into characters.

        :param value: An arbitrary string.
        """
        assert mapping_proxy_module._to_str_list(value) == ([] if value == "" else [value])


class TestTypeConverter:
    """Tests for :class:`TypeConverter`."""

    def test_stores_callables(self) -> None:
        """The two callables must be exposed as ``serialize`` / ``deserialize``."""
        converter = TypeConverter(str, str)
        assert converter.serialize is str
        assert converter.deserialize is str


# ---------------------------------------------------------------------------
# EnvironmentVariables
# ---------------------------------------------------------------------------


class TestEnvironmentVariables:
    """Tests for the dict-style :class:`EnvironmentVariables` proxy."""

    def test_set_item_coerces_to_string(self) -> None:
        """``[]`` assignment must persist the value as its string form."""
        backing: dict[str, str] = {}
        env = EnvironmentVariables(backing)
        env["PORT"] = 5678
        assert backing["PORT"] == "5678"
        assert env["PORT"] == "5678"

    def test_missing_key_raises_keyerror(self) -> None:
        """Reading an absent variable via ``[]`` must raise :exc:`KeyError`."""
        with pytest.raises(KeyError):
            _ = EnvironmentVariables({})["ABSENT"]

    def test_get_returns_default_when_absent(self) -> None:
        """:meth:`EnvironmentVariables.get` must return the default for an absent variable."""
        assert EnvironmentVariables({}).get("ABSENT", "fallback") == "fallback"

    @pytest.mark.parametrize(
        ("raw", "cast", "expected"),
        [
            ("1", bool, True),
            ("off", bool, False),
            ("5680", int, 5680),
            ("1.5", float, 1.5),
            ("plain", str, "plain"),
        ],
        ids=["bool-true", "bool-false", "int", "float", "str"],
    )
    def test_get_typed_cast(self, raw: str, cast: type, expected: object) -> None:
        """
        ``get(..., cast=)`` must convert the stored string via the converter registry.

        :param raw: The stored string value.
        :param cast: The requested type.
        :param expected: The expected converted value.
        """
        assert EnvironmentVariables({"VAR": raw}).get("VAR", cast=cast) == expected

    def test_get_cast_path(self) -> None:
        """``get(..., cast=Path)`` must rebuild a :class:`~pathlib.Path` from the value."""
        path = Path("x") / "y"
        assert EnvironmentVariables({"P": str(path)}).get("P", cast=Path) == path

    def test_contains_iter_and_len(self) -> None:
        """``in``, iteration and :func:`~builtins.len` must reflect the backing variables."""
        env = EnvironmentVariables({"A": "1", "B": "2"})
        assert "A" in env
        assert set(env) == {"A", "B"}
        assert len(env) == 2

    def test_delete_removes_variable(self) -> None:
        """``del`` must remove a present variable from the backing environment."""
        backing = {"GONE": "1"}
        del EnvironmentVariables(backing)["GONE"]
        assert "GONE" not in backing

    def test_delete_missing_raises_keyerror(self) -> None:
        """Deleting an absent variable must raise :exc:`KeyError`."""
        with pytest.raises(KeyError):
            del EnvironmentVariables({})["ABSENT"]

    def test_defaults_to_os_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        With no backing argument the proxy must read the live :data:`os.environ`.

        :param monkeypatch: Fixture used to set the process environment variable.
        """
        monkeypatch.setenv("STRATIFIED_PACKAGER_TEST_PORT", "5681")
        assert EnvironmentVariables().get("STRATIFIED_PACKAGER_TEST_PORT", cast=int) == 5681


class TestEnvVarDescriptors:
    """Tests for :class:`EnvVar` descriptors via :class:`_ExampleEnv`."""

    @pytest.mark.parametrize(
        ("attr", "default"),
        [
            ("FLAG", False),
            ("COUNT", 3),
            ("RATIO", 1.5),
            ("LABEL", "def"),
            ("ROOT", Path("base")),
        ],
        ids=["bool", "int", "float", "str", "path"],
    )
    def test_default_returned_when_unset(self, attr: str, default: object) -> None:
        """
        An unset variable must read back its declared default.

        :param attr: The descriptor attribute name.
        :param default: The expected default value.
        """
        assert getattr(_ExampleEnv({}), attr) == default

    @pytest.mark.parametrize(
        ("attr", "value"),
        [
            ("FLAG", True),
            ("COUNT", 42),
            ("RATIO", 9.25),
            ("LABEL", "changed"),
            ("ROOT", Path("x") / "y"),
        ],
        ids=["bool", "int", "float", "str", "path"],
    )
    def test_set_then_get_roundtrip(self, attr: str, value: object) -> None:
        """
        A written value must be read back unchanged through the same backing.

        :param attr: The descriptor attribute name.
        :param value: The value to write.
        """
        env = _ExampleEnv({})
        setattr(env, attr, value)
        assert getattr(env, attr) == value

    def test_class_access_returns_descriptor(self) -> None:
        """Accessing a variable on the class must return the :class:`EnvVar` descriptor."""
        assert isinstance(_ExampleEnv.FLAG, BoolEnvVar)

    def test_write_coerces_to_string_in_environ(self) -> None:
        """A descriptor write must store the value as a string in the backing environment."""
        backing: dict[str, str] = {}
        _ExampleEnv(backing).COUNT = 42
        assert backing["COUNT"] == "42"

    def test_descriptor_and_dict_access_agree(self) -> None:
        """The descriptor and the matching dict key must resolve to the same variable."""
        env = _ExampleEnv({})
        env.FLAG = True
        assert env.get("FLAG", cast=bool) is True
        assert env["FLAG"] == "True"

    def test_explicit_key_overrides_attribute_name(self) -> None:
        """A descriptor with an explicit ``key`` must read and write under that key."""
        backing: dict[str, str] = {}
        env = _ExampleEnv(backing)
        env.LABEL = "v"
        assert backing["CUSTOM_LABEL"] == "v"
        assert env.LABEL == "v"

    def test_attribute_name_is_default_key(self) -> None:
        """A descriptor without an explicit key must use its attribute name."""
        assert _ExampleEnv.COUNT.key == "COUNT"

    def test_reset_unsets_variable(self) -> None:
        """:meth:`EnvVar.reset` must unset the variable so the default returns."""
        env = _ExampleEnv({})
        env.COUNT = 99
        _ExampleEnv.COUNT.reset(env)
        assert env.COUNT == 3
        assert "COUNT" not in env
