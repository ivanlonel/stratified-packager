"""
Test suite for :mod:`stratified_packager.toolbelt.settings`.

Tooling
-------
* **pytest-qgis** — provides the session-scoped ``qgis_app`` fixture plus
    ``qgis_new_project`` (used to reset :class:`~qgis.core.QgsProject` state
    between project-scoped tests).

All tests require a running QGIS and are marked ``qgis`` via the module-level
:data:`pytestmark`. The proxies persist to the QGIS settings backend and the
open project, so an autouse fixture scrubs the test-only namespaces between
tests and a dedicated fixture snapshots/restores the real plugin keys.
"""
# pylint: disable=redefined-outer-name

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import hypothesis
import pytest
from hypothesis import strategies as st

pytest.importorskip("qgis", reason="The toolbelt settings proxies persist to the QGIS backend.")

# Imported only after the importorskip guard above confirms QGIS is available.
from qgis.core import QgsProject, QgsSettings, QgsSettingsTree, QgsVectorLayer
from qgis.PyQt.QtGui import QColor

import stratified_packager.toolbelt.settings as settings_module
from stratified_packager.toolbelt.mapping_proxy import from_storage, to_storage
from stratified_packager.toolbelt.settings import (
    BoolSetting,
    ColorSetting,
    DoubleSetting,
    EnumSetting,
    IntSetting,
    LayerCustomProperties,
    LayerVariables,
    PluginSettingsBase,
    ProjectEntries,
    ProjectVariables,
    SettingsProxy,
    StringListSetting,
    StringSetting,
    VariantMapSetting,
)

from ._conversion_samples import PURE_PROPERTY, Perm, Speed

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.qgis
"""Marks the whole module as requiring a QGIS runtime."""

_TEST_PLUGIN: str = "pytest_stratified_packager"
"""Fake plugin name so descriptor entries register under a disposable tree node."""

_TEST_GROUP: str = "pytest_strat"
"""Disposable :class:`~qgis.core.QgsSettings` group used by the dict-style tests."""


class _ExampleSettings(PluginSettingsBase):
    """Disposable settings schema exercising every :class:`Setting` subclass."""

    _PLUGIN_NAME: ClassVar[str] = _TEST_PLUGIN

    flag = BoolSetting(default=True, description="A boolean.")
    count = IntSetting(default=3, description="An integer.")
    ratio = DoubleSetting(default=1.5, description="A float.")
    label = StringSetting(default="def", key="custom_label_key")
    tags = StringListSetting(default=["a", "b"])
    color = ColorSetting(default=QColor("red"))
    speed = EnumSetting(Speed, default=Speed.SLOW)
    perms = EnumSetting(Perm, default=Perm.READ)
    vmap = VariantMapSetting(default={"k": 1})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _scrub_test_namespace() -> Generator[None, None, None]:
    """
    Remove the test-only settings namespaces before and after each test.

    :return: Nothing; yields control to the test body.
    """

    def _scrub() -> None:
        settings = QgsSettings()
        settings.remove(_TEST_GROUP)
        settings.remove(f"plugins/{_TEST_PLUGIN}")
        QgsSettingsTree.unregisterPluginTreeNode(_TEST_PLUGIN)
        _ExampleSettings.teardown()

    _scrub()
    yield
    _scrub()


@pytest.fixture
def memory_layer() -> QgsVectorLayer:
    """
    Return a fresh in-memory point layer for layer-proxy tests.

    :return: A valid in-memory :class:`~qgis.core.QgsVectorLayer`.
    """
    return QgsVectorLayer("Point?crs=EPSG:4326", "test_layer", "memory")


# ---------------------------------------------------------------------------
# __all__ completeness
# ---------------------------------------------------------------------------


def test_all_symbols_are_importable() -> None:
    """Every name in ``__all__`` must be importable from the module."""
    for name in settings_module.__all__:
        assert hasattr(settings_module, name), f"__all__ lists {name!r} but it is missing."


# ---------------------------------------------------------------------------
# QColor converter (registered by the settings module)
# ---------------------------------------------------------------------------


class TestQColorConverter:
    """Tests for the :class:`~qgis.PyQt.QtGui.QColor` converter this module registers at import."""

    @PURE_PROPERTY
    @hypothesis.given(
        red=st.integers(min_value=0, max_value=255),
        green=st.integers(min_value=0, max_value=255),
        blue=st.integers(min_value=0, max_value=255),
        alpha=st.integers(min_value=0, max_value=255),
    )
    def test_qcolor_roundtrip(self, red: int, green: int, blue: int, alpha: int) -> None:
        """
        A colour must round-trip via its ``#AARRGGBB`` name through the shared registry.

        :param red: Red channel (0-255).
        :param green: Green channel (0-255).
        :param blue: Blue channel (0-255).
        :param alpha: Alpha channel (0-255).
        """
        color = QColor(red, green, blue, alpha)
        assert from_storage(to_storage(color), QColor) == color


# ---------------------------------------------------------------------------
# Typed descriptors
# ---------------------------------------------------------------------------


class TestSettingDescriptors:
    """Tests for :class:`Setting` and its subclasses via :class:`_ExampleSettings`."""

    @pytest.mark.parametrize(
        ("attr", "default"),
        [
            ("flag", True),
            ("count", 3),
            ("ratio", 1.5),
            ("label", "def"),
            ("tags", ["a", "b"]),
            ("speed", Speed.SLOW),
            ("perms", Perm.READ),
            ("vmap", {"k": 1}),
        ],
        ids=["bool", "int", "double", "string", "stringlist", "enum", "intflag", "variantmap"],
    )
    def test_default_returned_when_unset(self, attr: str, default: object) -> None:
        """
        An unwritten setting must read back its declared default.

        :param attr: The descriptor attribute name.
        :param default: The expected default value.
        """
        assert getattr(_ExampleSettings(), attr) == default

    @pytest.mark.parametrize(
        ("attr", "value"),
        [
            ("flag", False),
            ("count", 42),
            ("ratio", 9.25),
            ("label", "changed"),
            ("tags", ["x", "y", "z"]),
            ("speed", Speed.FAST),
            ("perms", Perm.READ | Perm.WRITE),
            ("vmap", {"name": "x", "n": 3, "flag": True, "tags": ["p", "q"]}),
        ],
        ids=["bool", "int", "double", "string", "stringlist", "enum", "intflag", "variantmap"],
    )
    def test_set_then_get_roundtrip(self, attr: str, value: object) -> None:
        """
        A written value must be read back unchanged by a fresh proxy instance.

        :param attr: The descriptor attribute name.
        :param value: The value to write.
        """
        setattr(_ExampleSettings(), attr, value)
        assert getattr(_ExampleSettings(), attr) == value

    def test_color_roundtrip(self) -> None:
        """A :class:`ColorSetting` must round-trip a :class:`~qgis.PyQt.QtGui.QColor`."""
        example = _ExampleSettings()
        example.color = QColor(10, 20, 30)
        assert _ExampleSettings().color == QColor(10, 20, 30)

    def test_class_access_returns_descriptor(self) -> None:
        """Accessing a setting on the class must return the :class:`Setting` descriptor."""
        assert isinstance(_ExampleSettings.flag, BoolSetting)

    def test_reset_restores_default(self) -> None:
        """:meth:`Setting.reset` must drop the stored value so the default returns."""
        example = _ExampleSettings()
        example.count = 99
        _ExampleSettings.count.reset(_ExampleSettings)
        assert _ExampleSettings().count == 3

    def test_explicit_key_overrides_attribute_name(self) -> None:
        """A descriptor with an explicit ``key`` must store under that key."""
        example = _ExampleSettings()
        example.label = "v"
        assert example["custom_label_key"] == "v"

    def test_attribute_name_is_default_key(self) -> None:
        """A descriptor without an explicit key must use its attribute name."""
        assert _ExampleSettings.count.key == "count"


# ---------------------------------------------------------------------------
# SettingsProxy
# ---------------------------------------------------------------------------


class TestSettingsProxy:
    """Tests for the dict-style :class:`SettingsProxy`."""

    @pytest.fixture
    def proxy(self) -> SettingsProxy:
        """
        Return a proxy scoped to the disposable test group.

        :return: A :class:`SettingsProxy` rooted at :data:`_TEST_GROUP`.
        """
        return SettingsProxy(prefix=_TEST_GROUP)

    def test_set_and_get_item(self, proxy: SettingsProxy) -> None:
        """
        ``[]`` assignment must persist and read back the value.

        :param proxy: The scoped proxy under test.
        """
        proxy["theme"] = "dark"
        assert proxy["theme"] == "dark"

    def test_missing_key_raises_keyerror(self, proxy: SettingsProxy) -> None:
        """
        Reading an absent key via ``[]`` must raise :exc:`KeyError`.

        :param proxy: The scoped proxy under test.
        """
        with pytest.raises(KeyError):
            _ = proxy["absent"]

    def test_get_returns_default_when_absent(self, proxy: SettingsProxy) -> None:
        """
        :meth:`SettingsProxy.get` must return the default for an absent key.

        :param proxy: The scoped proxy under test.
        """
        assert proxy.get("absent", "fallback") == "fallback"

    @pytest.mark.parametrize(
        ("value", "cast", "expected"),
        [
            (5, int, 5),
            (2.5, float, 2.5),
            (True, bool, True),
            (["a", "b"], list, ["a", "b"]),
        ],
        ids=["int", "float", "bool", "list"],
    )
    def test_get_native_cast(
        self, proxy: SettingsProxy, value: object, cast: type, expected: object
    ) -> None:
        """
        ``get(..., cast=)`` must coerce native types via :meth:`QgsSettings.value`.

        :param proxy: The scoped proxy under test.
        :param value: The value to store.
        :param cast: The requested type.
        :param expected: The expected coerced value.
        """
        proxy["k"] = value
        assert proxy.get("k", cast=cast) == expected

    def test_get_custom_cast_via_converter(self, proxy: SettingsProxy) -> None:
        """
        ``get(..., cast=Path)`` must rebuild a :class:`~pathlib.Path` from the store.

        :param proxy: The scoped proxy under test.
        """
        path = Path("x") / "y"
        proxy["p"] = path
        assert proxy.get("p", cast=Path) == path

    def test_contains_and_delete(self, proxy: SettingsProxy) -> None:
        """
        ``in`` must reflect presence and ``del`` must remove the key.

        :param proxy: The scoped proxy under test.
        """
        proxy["k"] = 1
        assert "k" in proxy
        del proxy["k"]
        assert "k" not in proxy

    def test_delete_missing_raises_keyerror(self, proxy: SettingsProxy) -> None:
        """
        Deleting an absent key must raise :exc:`KeyError`.

        :param proxy: The scoped proxy under test.
        """
        with pytest.raises(KeyError):
            del proxy["absent"]

    def test_iter_and_len(self, proxy: SettingsProxy) -> None:
        """
        Iteration and :func:`~builtins.len` must reflect the stored keys.

        :param proxy: The scoped proxy under test.
        """
        proxy["a"] = 1
        proxy["b"] = 2
        assert set(proxy) == {"a", "b"}
        assert len(proxy) == 2

    def test_empty_prefix_addresses_raw_namespace(self) -> None:
        """An empty prefix must address keys without a leading group."""
        proxy = SettingsProxy()
        proxy[f"{_TEST_GROUP}/raw"] = "v"
        assert QgsSettings().value(f"{_TEST_GROUP}/raw") == "v"


# ---------------------------------------------------------------------------
# PluginSettingsBase
# ---------------------------------------------------------------------------


class TestPluginSettingsBase:
    """Tests for the descriptor-schema base :class:`PluginSettingsBase`."""

    def test_declares_expected_descriptors(self) -> None:
        """The example schema must expose its declared descriptors."""
        assert isinstance(_ExampleSettings.flag, BoolSetting)
        assert isinstance(_ExampleSettings.label, StringSetting)

    def test_scope_places_keys_under_plugin_node(self) -> None:
        """A descriptor write must land at ``plugins/<name>/<key>`` in QgsSettings."""
        _ExampleSettings().flag = False
        assert QgsSettings().value(f"plugins/{_TEST_PLUGIN}/flag", type=bool) is False

    def test_descriptor_and_dict_access_agree(self) -> None:
        """The descriptor and the matching dict key must resolve to the same value."""
        settings = _ExampleSettings()
        settings.flag = False
        assert settings.get("flag", cast=bool) is False

    def test_reset_defaults(self) -> None:
        """:meth:`PluginSettingsBase.reset_defaults` must restore declared defaults."""
        settings = _ExampleSettings()
        settings.flag = False
        settings.reset_defaults()
        assert settings.flag is True

    def test_empty_plugin_name_rejected(self) -> None:
        """Defining a concrete subclass without a ``_PLUGIN_NAME`` must raise at class creation."""
        with pytest.raises(TypeError, match="_PLUGIN_NAME"):

            class _Nameless(PluginSettingsBase):
                pass

    def test_abstract_subclass_allowed(self) -> None:
        """An ``abstract=True`` subclass may leave ``_PLUGIN_NAME`` unset."""

        class _AbstractSchema(PluginSettingsBase, abstract=True):
            shared = BoolSetting(default=True)

        class _ConcreteSchema(_AbstractSchema):
            _PLUGIN_NAME: ClassVar[str] = _TEST_PLUGIN

        assert isinstance(_ConcreteSchema.shared, BoolSetting)


class TestTeardown:
    """Tests for :meth:`PluginSettingsBase.teardown`."""

    def test_teardown_is_idempotent(self) -> None:
        """Repeated teardown calls must not raise, even with nothing registered."""
        _ExampleSettings.teardown()
        _ExampleSettings.teardown()

    def test_entry_rebuilt_after_teardown(self) -> None:
        """A setting must remain usable after its tree node is torn down."""
        _ExampleSettings().count = 11
        _ExampleSettings.teardown()
        assert _ExampleSettings().count == 11


# ---------------------------------------------------------------------------
# ProjectEntries
# ---------------------------------------------------------------------------


class TestProjectEntries:
    """Tests for :class:`ProjectEntries`."""

    @pytest.fixture
    def entries(self, qgis_new_project: QgsProject) -> ProjectEntries:
        """
        Return a project-entries proxy on a freshly reset project.

        :param qgis_new_project: pytest-qgis fixture resetting project state.
        :return: A :class:`ProjectEntries` scoped to the test group.
        """
        return ProjectEntries(scope=_TEST_GROUP, project=qgis_new_project)

    @pytest.mark.parametrize(
        ("value", "cast", "expected"),
        [
            ("hello", str, "hello"),
            (7, int, 7),
            (2.5, float, 2.5),
            (True, bool, True),
            (["a", "b"], list, ["a", "b"]),
        ],
        ids=["str", "int", "float", "bool", "list"],
    )
    def test_set_then_typed_get(
        self, entries: ProjectEntries, value: object, cast: type, expected: object
    ) -> None:
        """
        Each storable type must round-trip through the matching typed read.

        :param entries: The project-entries proxy.
        :param value: The value to store.
        :param cast: The type used to read it back.
        :param expected: The expected value.
        """
        entries["k"] = value
        assert entries.get("k", cast=cast) == expected

    def test_set_non_list_iterable_stored_as_list(self, entries: ProjectEntries) -> None:
        """
        A non-list iterable value must be stored element-wise and read back as a list.

        :param entries: The project-entries proxy.
        """
        entries["k"] = ("a", "b")
        assert entries.get("k", cast=list) == ["a", "b"]

    def test_getitem_returns_string(self, entries: ProjectEntries) -> None:
        """
        Plain ``[]`` access must return the entry as a string.

        :param entries: The project-entries proxy.
        """
        entries["name"] = "value"
        assert entries["name"] == "value"

    def test_missing_key_raises(self, entries: ProjectEntries) -> None:
        """
        Reading an absent entry via ``[]`` must raise :exc:`KeyError`.

        :param entries: The project-entries proxy.
        """
        with pytest.raises(KeyError):
            _ = entries["absent"]

    def test_get_absent_returns_default(self, entries: ProjectEntries) -> None:
        """
        A typed read of an absent key must return the default.

        :param entries: The project-entries proxy.
        """
        assert entries.get("absent", -1, cast=int) == -1

    def test_contains_iter_delete(self, entries: ProjectEntries) -> None:
        """
        Membership, iteration, and deletion must behave consistently.

        :param entries: The project-entries proxy.
        """
        entries["a"] = "1"
        entries["b"] = "2"
        assert "a" in entries
        assert set(entries) == {"a", "b"}
        del entries["a"]
        assert "a" not in entries

    def test_delete_missing_raises(self, entries: ProjectEntries) -> None:
        """
        Deleting an absent entry must raise :exc:`KeyError`.

        :param entries: The project-entries proxy.
        """
        with pytest.raises(KeyError):
            del entries["absent"]


# ---------------------------------------------------------------------------
# ProjectVariables
# ---------------------------------------------------------------------------


class TestProjectVariables:
    """Tests for :class:`ProjectVariables`."""

    @pytest.fixture
    def variables(self, qgis_new_project: QgsProject) -> ProjectVariables:
        """
        Return a project-variables proxy on a freshly reset project.

        :param qgis_new_project: pytest-qgis fixture resetting project state.
        :return: A :class:`ProjectVariables` instance.
        """
        return ProjectVariables(project=qgis_new_project)

    def test_set_get_delete(self, variables: ProjectVariables) -> None:
        """
        A user variable must round-trip and then be removable.

        :param variables: The project-variables proxy.
        """
        variables["region"] = "south"
        assert variables["region"] == "south"
        assert "region" in variables
        del variables["region"]
        assert "region" not in variables

    def test_iteration_includes_builtins(self, variables: ProjectVariables) -> None:
        """
        Iteration must surface QGIS' built-in project variables.

        :param variables: The project-variables proxy.
        """
        assert any(name.startswith("project_") for name in variables)

    def test_missing_variable_raises(self, variables: ProjectVariables) -> None:
        """
        Reading an absent variable via ``[]`` must raise :exc:`KeyError`.

        :param variables: The project-variables proxy.
        """
        with pytest.raises(KeyError):
            _ = variables["definitely_absent"]


# ---------------------------------------------------------------------------
# Layer proxies
# ---------------------------------------------------------------------------


class TestLayerVariables:
    """Tests for :class:`LayerVariables`."""

    def test_set_get_delete(self, memory_layer: QgsVectorLayer) -> None:
        """
        A user layer variable must round-trip and then be removable.

        :param memory_layer: A fresh in-memory layer.
        """
        variables = LayerVariables(memory_layer)
        variables["zone"] = "A"
        assert variables["zone"] == "A"
        assert "zone" in variables
        del variables["zone"]
        assert "zone" not in variables

    def test_delete_only_drops_target(self, memory_layer: QgsVectorLayer) -> None:
        """
        Deleting one variable must leave the others intact.

        :param memory_layer: A fresh in-memory layer.
        """
        variables = LayerVariables(memory_layer)
        variables["keep"] = "1"
        variables["drop"] = "2"
        del variables["drop"]
        assert variables["keep"] == "1"
        assert "drop" not in variables


class TestLayerCustomProperties:
    """Tests for :class:`LayerCustomProperties`."""

    def test_set_get_delete(self, memory_layer: QgsVectorLayer) -> None:
        """
        A custom property must round-trip and then be removable.

        :param memory_layer: A fresh in-memory layer.
        """
        properties = LayerCustomProperties(memory_layer)
        properties["alias"] = "Roads"
        assert properties["alias"] == "Roads"
        assert "alias" in properties
        del properties["alias"]
        assert "alias" not in properties

    def test_keys_and_len(self, memory_layer: QgsVectorLayer) -> None:
        """
        Iteration and :func:`~builtins.len` must reflect the stored properties.

        :param memory_layer: A fresh in-memory layer.
        """
        properties = LayerCustomProperties(memory_layer)
        properties["one"] = 1
        properties["two"] = 2
        assert set(properties) == {"one", "two"}
        assert len(properties) == 2

    def test_missing_property_raises(self, memory_layer: QgsVectorLayer) -> None:
        """
        Reading an absent property via ``[]`` must raise :exc:`KeyError`.

        :param memory_layer: A fresh in-memory layer.
        """
        with pytest.raises(KeyError):
            _ = LayerCustomProperties(memory_layer)["absent"]
