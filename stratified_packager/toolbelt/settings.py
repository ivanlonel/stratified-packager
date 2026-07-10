"""
QGIS-specific persistence proxies: typed settings, project entries, variables, layer properties.

This module wraps the disparate QGIS persistence APIs documented in the PyQGIS Developer
Cookbook (*Reading and Storing Settings*) behind a small set of Pythonic objects that read
and write values while converting to and from the appropriate Python types:

================================  =======================================================
Proxy                             Backing QGIS API
================================  =======================================================
:class:`SettingsProxy`            :class:`qgis.core.QgsSettings` (flat key/value)
:class:`PluginSettingsBase`       the above plus typed ``QgsSettingsEntry*`` objects
:class:`ProjectEntries`           :meth:`qgis.core.QgsProject.readEntry` / ``writeEntry``
:class:`ProjectVariables`         :class:`qgis.core.QgsExpressionContextUtils` project scope
:class:`LayerCustomProperties`    :meth:`qgis.core.QgsMapLayer.customProperty`
:class:`LayerVariables`           :class:`qgis.core.QgsExpressionContextUtils` layer scope
================================  =======================================================

Two complementary access styles are offered, mirroring how
``QgsSettingsEntry*`` sits over a flat store:

* **Dict-like** — every proxy is a :class:`~collections.abc.MutableMapping`
  keyed by string, so arbitrary dynamic keys work out of the box::

      gs = SettingsProxy()
      gs["ui/theme"]  # raw stored value
      gs.get("max_threads", 4, cast=int)  # with type and default

* **Typed descriptors** — :class:`PluginSettingsBase` subclasses declare known keys as class
  attributes whose :class:`Setting` descriptors read and write typed ``QgsSettingsEntry*``
  objects registered under the plugin's node in the global settings tree::

      class MySettings(PluginSettingsBase):
          _PLUGIN_NAME = "my_plugin"
          debug_mode = BoolSetting(default=False)


      s = MySettings()
      s.debug_mode  # -> bool
      s.debug_mode = True  # persisted

The proxies build on the QGIS-free :mod:`.mapping_proxy`: they subclass its
:class:`~.mapping_proxy.MappingProxy` and read and write through its conversion registry
(:func:`~.mapping_proxy.to_storage` / :func:`~.mapping_proxy.from_storage`). That registry
covers the stdlib types; this module registers the QGIS-only :class:`~qgis.PyQt.QtGui.QColor`
converter at import so :class:`ColorSetting` and ``cast=QColor`` round-trip.

.. warning::
    Every proxy here touches main-thread QGIS objects (:class:`~qgis.core.QgsProject`,
    :class:`~qgis.core.QgsMapLayer`), so they must only be used on the GUI thread.
    :class:`qgis.core.QgsSettings` is the sole exception (it is thread-safe), but
    the proxies make no special accommodation for off-thread use.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, ClassVar, overload, override
from typing import cast as _cast

from qgis.core import (
    QgsExpressionContextScope,
    QgsExpressionContextUtils,
    QgsMapLayer,
    QgsProject,
    QgsSettings,
    QgsSettingsEntryBase,
    QgsSettingsEntryBool,
    QgsSettingsEntryColor,
    QgsSettingsEntryDouble,
    QgsSettingsEntryInteger,
    QgsSettingsEntryString,
    QgsSettingsEntryStringList,
    QgsSettingsEntryVariant,
    QgsSettingsEntryVariantMap,
    QgsSettingsTree,
)
from qgis.PyQt import sip
from qgis.PyQt.QtGui import QColor

# _is_item_iterable / _to_str_list are shared coercion helpers reused by the QGIS proxies.
from .mapping_proxy import (
    MappingProxy,
    _is_item_iterable,
    _to_str_list,
    from_storage,
    register_converter,
)

__all__: list[str] = [
    "BoolSetting",
    "ColorSetting",
    "DoubleSetting",
    "EnumSetting",
    "IntSetting",
    "LayerCustomProperties",
    "LayerVariables",
    "PluginSettingsBase",
    "ProjectEntries",
    "ProjectVariables",
    "Setting",
    "SettingsProxy",
    "StringListSetting",
    "StringSetting",
    "VariantMapSetting",
    "VariantSetting",
]


# ---------------------------------------------------------------------------
# QGIS-type converter registration
# ---------------------------------------------------------------------------

# QColor lives in qgis.PyQt, so its converter is registered here rather than in the
# QGIS-free mapping_proxy module; importing this module makes cast=QColor round-trip.
register_converter(
    QColor,
    lambda c: c.name(QColor.NameFormat.HexArgb),
    lambda r: r if isinstance(r, QColor) else QColor(str(r)),
)


# ---------------------------------------------------------------------------
# Typed descriptors over QgsSettingsEntry*
# ---------------------------------------------------------------------------


class Setting[T]:
    """
    Descriptor mapping a class attribute to a typed ``QgsSettingsEntry*``.

    Declare instances as class attributes of a :class:`PluginSettingsBase` subclass.
    On first access, the descriptor lazily constructs its backing entry using the *plugin*
    constructor of the relevant ``QgsSettingsEntry*`` class — keyed by the owning proxy's
    :attr:`PluginSettingsBase._PLUGIN_NAME` — so the value is persisted at
    ``plugins/<plugin-name>/<key>`` and appears in the QGIS settings tree. That key
    coincides with the one a :class:`SettingsProxy` prefixed with ``plugins/<plugin-name>``
    produces, so descriptor access and dict access address the same stored value.

    Subclasses set :attr:`_ENTRY_CLASS` to the concrete entry type; only
    :class:`EnumSetting` needs to override the value-marshalling hooks.
    """

    _ENTRY_CLASS: ClassVar[type[QgsSettingsEntryBase]]
    """Concrete ``QgsSettingsEntry*`` class backing this descriptor."""

    def __init__(self, default: T, description: str = "", *, key: str | None = None) -> None:
        """
        Initialize the descriptor.

        :param default: Value returned when the setting has never been written.
        :param description: Human-readable description stored on the entry.
        :param key: Storage key; defaults to the attribute name the descriptor is assigned to.
        """
        self._default: T = default
        self._description: str = description
        self._explicit_key: str | None = key
        self._name: str = ""
        self._entries: dict[type, QgsSettingsEntryVariant] = {}

    def __set_name__(self, owner: type, name: str) -> None:
        """
        Capture the attribute name to use as the default storage key.

        :param owner: The class the descriptor is assigned to.
        :param name: The attribute name the descriptor is bound to.
        """
        self._name = name

    @property
    def key(self) -> str:
        """
        Storage key of this setting (the explicit key, or the attribute name).

        :return: The key used under the plugin's settings node.
        """
        return self._explicit_key if self._explicit_key is not None else self._name

    def _build_entry(self, plugin_name: str) -> QgsSettingsEntryVariant:
        """
        Construct the backing entry under *plugin_name*'s settings node.

        The concrete entry is built from :attr:`_ENTRY_CLASS` and viewed as a
        :class:`~qgis.core.QgsSettingsEntryVariant` so its ``value`` / ``setValue``
        methods are visible to type checkers (the abstract base lacks them).

        :param plugin_name: Plugin name inserted into the entry key.
        :return: The backing entry, viewed as a variant entry.
        """
        entry = self._ENTRY_CLASS(self.key, plugin_name, self._default, self._description)
        return _cast("QgsSettingsEntryVariant", entry)

    def _entry(self, owner: type[PluginSettingsBase]) -> QgsSettingsEntryVariant:
        """
        Return the backing entry for *owner*, building and caching it on first use.

        :param owner: The :class:`PluginSettingsBase` subclass owning the descriptor.
        :return: The cached backing entry.
        """
        entry = self._entries.get(owner)
        if entry is None:
            # owner is the cooperating PluginSettingsBase subclass supplying the plugin name.
            entry = self._build_entry(owner._PLUGIN_NAME)  # noqa: SLF001
            # The plugin constructor registers the entry under the settings-tree node, which
            # owns and deletes it on teardown() → unregisterPluginTreeNode. Hand ownership to
            # C++ so Python's later GC of this wrapper can't double-free that already-deleted
            # entry — a segfault on some PyQt5/SIP builds.
            # PyQt6's sip.pyi mistypes transferto's owner as `wrapper` only, so None goes via cast.
            sip.transferto(entry, _cast("Any", None))
            self._entries[owner] = entry
        return entry

    def _decode(self, entry: QgsSettingsEntryVariant) -> T:
        """
        Marshal the entry's stored value into ``T``.

        :param entry: The backing entry to read.
        :return: The typed value.
        """
        value: T = entry.value()
        return value

    def _encode(self, value: T) -> object:
        """
        Marshal ``T`` into the form the entry persists.

        :param value: The value being assigned.
        :return: The representation passed to ``QgsSettingsEntryBase.setValue``.
        """
        return value

    @overload
    def __get__(self, instance: None, owner: type[PluginSettingsBase]) -> Setting[T]: ...

    @overload
    def __get__(self, instance: PluginSettingsBase, owner: type[PluginSettingsBase]) -> T: ...

    def __get__(
        self, instance: PluginSettingsBase | None, owner: type[PluginSettingsBase]
    ) -> Setting[T] | T:
        """
        Return the descriptor on class access, or the typed value on instance access.

        :param instance: The owning instance, or :data:`None` for class access.
        :param owner: The owning class.
        :return: ``self`` for class access, otherwise the decoded value.
        """
        if instance is None:
            return self
        return self._decode(self._entry(owner))

    def __set__(self, instance: PluginSettingsBase, value: T) -> None:
        """
        Persist *value* through the backing entry.

        :param instance: The owning instance.
        :param value: The value to store.
        :raise RuntimeError: If QGIS rejects the value (e.g. it fails the entry's validation).
        """
        if not self._entry(type(instance)).setValue(self._encode(value)):
            msg = f"QGIS rejected the value for setting {self.key!r}."
            raise RuntimeError(msg)

    def reset(self, owner: type[PluginSettingsBase]) -> None:
        """
        Remove the stored value so the default applies again.

        :param owner: The owning :class:`PluginSettingsBase` subclass.
        """
        self._entry(owner).remove()

    def _forget(self) -> None:
        """Drop cached entries so they are rebuilt after a settings-tree teardown."""
        self._entries.clear()


class StringSetting(Setting[str]):
    """A :class:`str` setting backed by :class:`~qgis.core.QgsSettingsEntryString`."""

    _ENTRY_CLASS: ClassVar[type[QgsSettingsEntryBase]] = QgsSettingsEntryString


class IntSetting(Setting[int]):
    """An :class:`int` setting backed by :class:`~qgis.core.QgsSettingsEntryInteger`."""

    _ENTRY_CLASS: ClassVar[type[QgsSettingsEntryBase]] = QgsSettingsEntryInteger


class DoubleSetting(Setting[float]):
    """A :class:`float` setting backed by :class:`~qgis.core.QgsSettingsEntryDouble`."""

    _ENTRY_CLASS: ClassVar[type[QgsSettingsEntryBase]] = QgsSettingsEntryDouble


class BoolSetting(Setting[bool]):
    """A :class:`bool` setting backed by :class:`~qgis.core.QgsSettingsEntryBool`."""

    _ENTRY_CLASS: ClassVar[type[QgsSettingsEntryBase]] = QgsSettingsEntryBool


class StringListSetting(Setting[list[str]]):
    """A ``list[str]`` setting backed by :class:`~qgis.core.QgsSettingsEntryStringList`."""

    _ENTRY_CLASS: ClassVar[type[QgsSettingsEntryBase]] = QgsSettingsEntryStringList


class ColorSetting(Setting[QColor]):
    """
    A :class:`~qgis.PyQt.QtGui.QColor` setting.

    Backed by :class:`~qgis.core.QgsSettingsEntryColor`.
    """

    _ENTRY_CLASS: ClassVar[type[QgsSettingsEntryBase]] = QgsSettingsEntryColor


class VariantSetting(Setting[object]):
    """A free-form setting backed by :class:`~qgis.core.QgsSettingsEntryVariant`."""

    _ENTRY_CLASS: ClassVar[type[QgsSettingsEntryBase]] = QgsSettingsEntryVariant


class VariantMapSetting(Setting[dict[str, Any]]):
    """
    A ``dict[str, Any]`` setting backed by :class:`~qgis.core.QgsSettingsEntryVariantMap`.

    Values round-trip type-preservingly (nested scalars and string lists keep
    their Python types). Like every descriptor this is read-replace: mutating
    the returned dict in place does **not** persist; reassign the whole value,
    e.g. ``proxy.conf = proxy.conf | {"key": value}``.
    """

    _ENTRY_CLASS: ClassVar[type[QgsSettingsEntryBase]] = QgsSettingsEntryVariantMap


class EnumSetting[E: Enum](Setting[E]):
    """
    An :class:`enum.Enum` setting persisted by its member ``value``.

    The backing ``QgsSettingsEntry*`` is chosen from the type of the default
    member's ``value`` (:class:`bool`/:class:`int`/:class:`float`/:class:`str`,
    falling back to :class:`~qgis.core.QgsSettingsEntryVariant`). Reading reconstructs the member
    via ``enum_type(stored_value)``, which also handles :class:`enum.IntFlag`
    combinations. This sidesteps the inconsistent return typing of
    ``QgsSettingsEntryEnumFlag`` while still persisting through a typed entry.
    """

    def __init__(
        self, enum_type: type[E], default: E, description: str = "", *, key: str | None = None
    ) -> None:
        """
        Initialize the descriptor.

        :param enum_type: The concrete :class:`enum.Enum` subclass.
        :param default: Default member.
        :param description: Human-readable description stored on the entry.
        :param key: Storage key; defaults to the attribute name.
        """
        super().__init__(default, description, key=key)
        self._enum_type: type[E] = enum_type

    @override
    def _build_entry(self, plugin_name: str) -> QgsSettingsEntryVariant:
        """
        Construct a typed entry storing the member value (see the class docstring).

        :param plugin_name: Plugin name inserted into the entry key.
        :return: A backing entry whose value type matches the enum's values.
        """
        entry_class: type[QgsSettingsEntryBase]
        match stored := self._default.value:
            case bool():  # bool is a subclass of int, so its case must precede int().
                entry_class = QgsSettingsEntryBool
            case int():
                entry_class = QgsSettingsEntryInteger
            case float():
                entry_class = QgsSettingsEntryDouble
            case str():
                entry_class = QgsSettingsEntryString
            case _:
                entry_class = QgsSettingsEntryVariant

        return _cast(
            "QgsSettingsEntryVariant",
            entry_class(self.key, plugin_name, stored, self._description),
        )

    @override
    def _decode(self, entry: QgsSettingsEntryVariant) -> E:
        """
        Rebuild the enum member from the stored value.

        :param entry: The backing entry to read.
        :return: The reconstructed enum member.
        """
        return self._enum_type(entry.value())

    @override
    def _encode(self, value: E) -> object:
        """
        Reduce the enum member to its stored value.

        :param value: The enum member being assigned.
        :return: ``value.value``.
        """
        return value.value


# ---------------------------------------------------------------------------
# Global settings
# ---------------------------------------------------------------------------


class SettingsProxy(MappingProxy):
    """
    Dict-like proxy over :class:`qgis.core.QgsSettings`, optionally scoped to a prefix.

    Keys are joined to *prefix* with ``/``; an empty prefix (the default)
    addresses the raw global namespace, so ``SettingsProxy()["ui/theme"]`` reads
    the same key the QGIS options dialog writes.

    For typed reads prefer :meth:`~.mapping_proxy.MappingProxy.get` with ``cast=`` — it routes
    the native types (:class:`str`, :class:`int`, :class:`float`, :class:`bool`, :class:`list`)
    through :meth:`qgis.core.QgsSettings.value`'s own coercion (which correctly turns the
    string ``"true"`` back into :data:`True`) and uses the converter registry for the rest.
    Plain ``[]`` access returns the raw stored value without coercion.
    """

    _NATIVE_TYPES: ClassVar[tuple[type, ...]] = (str, int, float, bool, list)
    """Types :meth:`qgis.core.QgsSettings.value` can coerce directly via its ``type=`` argument."""

    def __init__(self, prefix: str = "", *, settings: QgsSettings | None = None) -> None:
        """
        Initialize the proxy.

        :param prefix: Key prefix; surrounding slashes are stripped.
        :param settings: Existing :class:`~qgis.core.QgsSettings` to use; a fresh
            one is created when omitted.
        """
        self._prefix: str = prefix.strip("/")
        self._settings: QgsSettings = settings if settings is not None else QgsSettings()

    def _full_key(self, key: str) -> str:
        """
        Join *key* to the configured prefix.

        :param key: The relative key.
        :return: The fully qualified :class:`~qgis.core.QgsSettings` key.
        """
        return f"{self._prefix}/{key}" if self._prefix else key

    @override
    def _raw_get(self, key: str) -> tuple[object, bool]:
        """
        Read *key* from :class:`~qgis.core.QgsSettings`.

        :param key: The relative key.
        :return: A ``(value, present)`` pair.
        """
        full = self._full_key(key)
        if not self._settings.contains(full):
            return None, False
        return self._settings.value(full), True

    @override
    def _raw_set(self, key: str, value: object) -> None:
        """
        Write *value* at *key*.

        :param key: The relative key.
        :param value: The storable value.
        """
        # QGS202 targets QgsRasterBlock/QgsRasterAttributeTable; QgsSettings.setValue returns None.
        self._settings.setValue(self._full_key(key), value)  # noqa: QGS202

    @override
    def _raw_del(self, key: str) -> None:
        """
        Remove *key* and any sub-settings.

        :param key: The relative key.
        """
        self._settings.remove(self._full_key(key))

    @override
    def _raw_keys(self) -> list[str]:
        """
        Return the keys under the configured prefix, relative to it.

        :return: The list of relative keys.
        """
        if not self._prefix:
            return list(self._settings.allKeys())
        self._settings.beginGroup(self._prefix)
        try:
            return list(self._settings.allKeys())
        finally:
            self._settings.endGroup()

    @override
    def _typed_get(self, key: str, cast: type[object] | None) -> tuple[object, bool]:
        """
        Read *key*, coercing native types through :meth:`qgis.core.QgsSettings.value`.

        :param key: The relative key.
        :param cast: Target Python type, or :data:`None` for the raw value.
        :return: A ``(value, present)`` pair.
        """
        full = self._full_key(key)
        if not self._settings.contains(full):
            return None, False
        if cast is None:
            return self._settings.value(full), True
        if cast in self._NATIVE_TYPES:
            return self._settings.value(full, None, cast), True
        return from_storage(self._settings.value(full), cast), True


class PluginSettingsBase(SettingsProxy):
    """
    Plugin-agnostic base for a plugin's typed settings schema, scoped under ``plugins/<name>``.

    Concrete subclasses set a non-empty :attr:`_PLUGIN_NAME` and declare their known keys as typed
    :class:`Setting` descriptors while remaining a full dict-like :class:`SettingsProxy` for any
    additional keys. Because the scope matches the descriptors' entry keys, ``self.<key>`` and
    ``self["<key>"]`` address the same stored value. Everything is derived from
    :attr:`_PLUGIN_NAME`, so this class carries no dependency on any particular plugin. The name is
    enforced at class-creation time (see ``__init_subclass__``); an intermediate base that leaves
    it intentionally unset must opt out with ``class Mixin(PluginSettingsBase, abstract=True)``.
    """

    _PLUGIN_NAME: ClassVar[str]
    """Plugin name (tree node and scope); a concrete subclass MUST set a non-empty value."""

    @override
    def __init_subclass__(cls, *, abstract: bool = False, **kwargs: object) -> None:
        r"""
        Reject concrete subclasses that fail to set a non-empty :attr:`_PLUGIN_NAME`.

        :param abstract: When :data:`True`, skip the check so an intermediate base
            may leave :attr:`_PLUGIN_NAME` unset for its own concrete subclasses to fill.
        :param \*\*kwargs: Further keyword arguments forwarded to :meth:`object.__init_subclass__`.
        :raise TypeError: If a non-abstract subclass leaves :attr:`_PLUGIN_NAME` empty.
        """
        super().__init_subclass__(**kwargs)
        # getattr default covers the bare annotation: the base declares but never assigns it.
        if not abstract and not getattr(cls, "_PLUGIN_NAME", ""):
            msg = (
                f"{cls.__name__} must set a non-empty '_PLUGIN_NAME' "
                f"(or be declared with 'class {cls.__name__}(..., abstract=True)')."
            )
            raise TypeError(msg)

    def __init__(self, *, settings: QgsSettings | None = None) -> None:
        """
        Initialize the proxy scoped to the plugin's settings node.

        :param settings: Existing :class:`~qgis.core.QgsSettings` to use; a fresh
            one is created when omitted.
        """
        super().__init__(prefix=f"plugins/{self._PLUGIN_NAME}", settings=settings)

    @classmethod
    def teardown(cls) -> None:
        """
        Unregister the plugin's settings-tree node and drop cached descriptor entries.

        Call this from the plugin's ``unload()`` so a subsequent reload can re-register the
        same :class:`Setting` entries cleanly. Safe to call when nothing has been registered.
        """
        QgsSettingsTree.unregisterPluginTreeNode(cls._PLUGIN_NAME)
        for klass in cls.__mro__:
            for attr in vars(klass).values():
                if isinstance(attr, Setting):
                    # Setting cooperates with this proxy; dropping its cache is intentional.
                    attr._forget()  # noqa: SLF001

    def reset_defaults(self) -> None:
        """Remove every declared :class:`Setting`'s stored value, restoring its default."""
        owner = type(self)
        for klass in owner.__mro__:
            for attr in vars(klass).values():
                if isinstance(attr, Setting):
                    attr.reset(owner)


# ---------------------------------------------------------------------------
# Project entries
# ---------------------------------------------------------------------------


class ProjectEntries(MappingProxy):
    """
    Dict-like proxy over a project's custom entries (:meth:`qgis.core.QgsProject.writeEntry`).

    Entries are persisted in the ``.qgs``/``.qgz`` file under a caller-supplied *scope* (group).
    They are **not** exposed as expression variables — use :class:`ProjectVariables` for those.

    QGIS reads project entries through type-specific methods, so for typed reads use
    :meth:`~.mapping_proxy.MappingProxy.get` with ``cast=``; plain ``[]`` access returns the value
    as a string. Writes dispatch on the Python type to the matching ``writeEntry*`` method —
    :meth:`~qgis.core.QgsProject.writeEntryBool` / :meth:`~qgis.core.QgsProject.writeEntryDouble`
    for :class:`bool` / :class:`float`, and :meth:`~qgis.core.QgsProject.writeEntry` for
    everything else — so each value round-trips through its corresponding ``read*Entry``
    (e.g. read a float back with ``cast=float``). Iteration yields the immediate child
    entry keys of the scope; nested keys are reached with a proxy scoped one level deeper.
    """

    def __init__(self, scope: str, *, project: QgsProject | None = None) -> None:
        """
        Initialize the proxy.

        :param scope: Entry scope (group) name (e.g. the plugin slug).
        :param project: Project to read/write; defaults to :meth:`qgis.core.QgsProject.instance`.
        """
        self._scope: str = scope
        self._project: QgsProject = _resolve_project(project)

    @override
    def _raw_get(self, key: str) -> tuple[object, bool]:
        """
        Read *key* as a string from the project scope.

        :param key: The entry key.
        :return: A ``(value, present)`` pair.
        """
        return self._project.readEntry(self._scope, key)

    @override
    def _raw_set(self, key: str, value: object) -> None:
        """
        Write *value* at *key*, dispatching on the storable type.

        :param key: The entry key.
        :param value: The storable value already passed through :func:`~.mapping_proxy.to_storage`.
        :raise RuntimeError: If :class:`~qgis.core.QgsProject` reports the write failed.
        """
        if isinstance(value, bool):
            ok = self._project.writeEntryBool(self._scope, key, value)
        elif isinstance(value, (int, str)):
            ok = self._project.writeEntry(self._scope, key, value)
        elif isinstance(value, float):
            ok = self._project.writeEntryDouble(self._scope, key, value)
        elif _is_item_iterable(value):
            ok = self._project.writeEntry(self._scope, key, [str(item) for item in value])
        else:
            ok = self._project.writeEntry(self._scope, key, str(value))
        if not ok:
            msg = f"QgsProject failed to write entry {key!r} in scope {self._scope!r}."
            raise RuntimeError(msg)

    @override
    def _raw_del(self, key: str) -> None:
        """
        Remove *key* from the project scope.

        :param key: The entry key.
        :raise RuntimeError: If :class:`~qgis.core.QgsProject` reports the removal failed.
        """
        if not self._project.removeEntry(self._scope, key):
            msg = f"QgsProject failed to remove entry {key!r} in scope {self._scope!r}."
            raise RuntimeError(msg)

    @override
    def _raw_keys(self) -> list[str]:
        """
        Return the immediate child entry keys of the scope.

        :return: The list of entry keys holding values.
        """
        return list(self._project.entryList(self._scope, ""))

    @override
    def __getitem__(self, key: str) -> object:
        """
        Return the string value of entry *key*.

        :param key: The entry key.
        :return: The entry value read as a string.
        :raise KeyError: If *key* is not an entry of the scope.
        """
        if key not in self:
            raise KeyError(key)
        return self._project.readEntry(self._scope, key)[0]

    @override
    def __contains__(self, key: object) -> bool:
        """
        Report whether *key* is an entry of the scope.

        :param key: The candidate key.
        :return: :data:`True` if *key* is a present string entry key.
        """
        return isinstance(key, str) and key in self._raw_keys()

    @override
    def __delitem__(self, key: str) -> None:
        """
        Delete entry *key* from the scope.

        :param key: The entry key.
        :raise KeyError: If *key* is not present.
        """
        if key not in self:
            raise KeyError(key)
        self._raw_del(key)

    @override
    def _typed_get(self, key: str, cast: type[object] | None) -> tuple[object, bool]:
        """
        Read *key* with the :class:`~qgis.core.QgsProject` method matching *cast*.

        :class:`bool`, :class:`int`, :class:`float` and :class:`list` route to
        :meth:`~qgis.core.QgsProject.readBoolEntry`, :meth:`~qgis.core.QgsProject.readNumEntry`,
        :meth:`~qgis.core.QgsProject.readDoubleEntry` and
        :meth:`~qgis.core.QgsProject.readListEntry` respectively;
        other casts read the string entry and convert via :func:`~.mapping_proxy.from_storage`.

        :param key: The entry key.
        :param cast: Target Python type, or :data:`None` for the string value.
        :return: A ``(value, present)`` pair.
        """
        value: object
        ok: bool
        if cast is bool:
            value, ok = self._project.readBoolEntry(self._scope, key)
        elif cast is int:
            value, ok = self._project.readNumEntry(self._scope, key)
        elif cast is float:
            value, ok = self._project.readDoubleEntry(self._scope, key)
        elif cast is list:
            value, ok = self._project.readListEntry(self._scope, key)
        elif cast is None or cast is str:
            value, ok = self._project.readEntry(self._scope, key)
        else:
            raw, ok = self._project.readEntry(self._scope, key)
            value = from_storage(raw, cast) if ok else None
        return value, ok


# ---------------------------------------------------------------------------
# Expression-variable proxies
# ---------------------------------------------------------------------------


class ProjectVariables(MappingProxy):
    """
    Dict-like proxy over a project's expression variables.

    Wraps :class:`qgis.core.QgsExpressionContextUtils`' project scope — the
    ``@``-variables shown under *Project Properties → Variables*. Assignment
    creates or replaces a user-defined variable; deletion removes one.

    Iteration and membership reflect the **full** project scope, which also includes QGIS'
    built-in project variables (``project_path``, ``project_title``, …). Those built-ins
    are read-only: deleting a name that exists only as a built-in has no effect.
    """

    def __init__(self, *, project: QgsProject | None = None) -> None:
        """
        Initialize the proxy.

        :param project: Project to read/write; defaults to :meth:`qgis.core.QgsProject.instance`.
        """
        self._project: QgsProject = _resolve_project(project)

    def _scope(self) -> QgsExpressionContextScope:
        """
        Return a fresh project expression scope.

        :return: The project :class:`~qgis.core.QgsExpressionContextScope`.
        :raise RuntimeError: If QGIS returns no project scope.
        """
        scope = QgsExpressionContextUtils.projectScope(self._project)
        if scope is None:
            msg = "QGIS returned no project expression scope."
            raise RuntimeError(msg)
        return scope

    @override
    def _raw_get(self, key: str) -> tuple[object, bool]:
        """
        Read variable *key* from the project scope.

        :param key: The variable name.
        :return: A ``(value, present)`` pair.
        """
        scope = self._scope()
        if not scope.hasVariable(key):
            return None, False
        return scope.variable(key), True

    @override
    def _raw_set(self, key: str, value: object) -> None:
        """
        Set the user-defined project variable *key*.

        :param key: The variable name.
        :param value: The storable value.
        """
        QgsExpressionContextUtils.setProjectVariable(self._project, key, value)

    @override
    def _raw_del(self, key: str) -> None:
        """
        Remove the user-defined project variable *key*.

        :param key: The variable name.
        """
        QgsExpressionContextUtils.removeProjectVariable(self._project, key)

    @override
    def _raw_keys(self) -> list[str]:
        """
        Return all variable names in the project scope (custom and built-in).

        :return: The list of variable names.
        """
        return list(self._scope().variableNames())


class LayerVariables(MappingProxy):
    """
    Dict-like proxy over a layer's expression variables.

    Wraps :class:`qgis.core.QgsExpressionContextUtils`' layer scope — the
    ``@``-variables shown under *Layer Properties → Variables*.

    As with :class:`ProjectVariables`, iteration and membership reflect the full layer
    scope (including built-ins such as ``layer_name``/``layer_id``). QGIS exposes no
    ``removeLayerVariable``, so deletion rewrites the layer's user-defined variables without
    the removed key via :meth:`qgis.core.QgsExpressionContextUtils.setLayerVariables`;
    deleting a name that exists only as a built-in therefore has no effect.
    """

    _VARIABLE_NAMES_PROPERTY: ClassVar[str] = "variableNames"
    """Custom-property key under which QGIS stores user-defined variable names."""

    _VARIABLE_VALUES_PROPERTY: ClassVar[str] = "variableValues"
    """Custom-property key under which QGIS stores user-defined variable values."""

    def __init__(self, layer: QgsMapLayer) -> None:
        """
        Initialize the proxy.

        :param layer: The layer whose variables are proxied.
        """
        self._layer: QgsMapLayer = layer

    def _scope(self) -> QgsExpressionContextScope:
        """
        Return a fresh layer expression scope.

        :return: The layer :class:`~qgis.core.QgsExpressionContextScope`.
        :raise RuntimeError: If QGIS returns no layer scope.
        """
        scope = QgsExpressionContextUtils.layerScope(self._layer)
        if scope is None:
            msg = "QGIS returned no layer expression scope."
            raise RuntimeError(msg)
        return scope

    def _custom_pairs(self) -> dict[str, str]:
        """
        Return the layer's user-defined variables from its custom properties.

        :return: A mapping of user-defined variable names to their stored values.
        """
        names = _to_str_list(self._layer.customProperty(self._VARIABLE_NAMES_PROPERTY))
        values = _to_str_list(self._layer.customProperty(self._VARIABLE_VALUES_PROPERTY))
        return dict(zip(names, values, strict=False))

    @override
    def _raw_get(self, key: str) -> tuple[object, bool]:
        """
        Read variable *key* from the layer scope.

        :param key: The variable name.
        :return: A ``(value, present)`` pair.
        """
        scope = self._scope()
        if not scope.hasVariable(key):
            return None, False
        return scope.variable(key), True

    @override
    def _raw_set(self, key: str, value: object) -> None:
        """
        Set the user-defined layer variable *key*.

        :param key: The variable name.
        :param value: The storable value.
        """
        QgsExpressionContextUtils.setLayerVariable(self._layer, key, value)

    @override
    def _raw_del(self, key: str) -> None:
        """
        Remove the user-defined layer variable *key* by rewriting the rest.

        :param key: The variable name.
        """
        remaining: dict[str | None, Any] = {
            name: value for name, value in self._custom_pairs().items() if name != key
        }
        QgsExpressionContextUtils.setLayerVariables(self._layer, remaining)

    @override
    def _raw_keys(self) -> list[str]:
        """
        Return all variable names in the layer scope (custom and built-in).

        :return: The list of variable names.
        """
        return list(self._scope().variableNames())


# ---------------------------------------------------------------------------
# Layer custom properties
# ---------------------------------------------------------------------------


class LayerCustomProperties(MappingProxy):
    """
    Dict-like proxy over a layer's custom properties.

    Wraps :meth:`qgis.core.QgsMapLayer.customProperty` /
    :meth:`~qgis.core.QgsMapLayer.setCustomProperty` — arbitrary
    key/value pairs persisted with the layer in the project file.
    """

    def __init__(self, layer: QgsMapLayer) -> None:
        """
        Initialize the proxy.

        :param layer: The layer whose custom properties are proxied.
        """
        self._layer: QgsMapLayer = layer

    @override
    def _raw_get(self, key: str) -> tuple[object, bool]:
        """
        Read custom property *key*.

        :param key: The property key.
        :return: A ``(value, present)`` pair.
        """
        if key not in self._layer.customPropertyKeys():
            return None, False
        return self._layer.customProperty(key), True

    @override
    def _raw_set(self, key: str, value: object) -> None:
        """
        Set custom property *key*.

        :param key: The property key.
        :param value: The storable value.
        """
        self._layer.setCustomProperty(key, value)

    @override
    def _raw_del(self, key: str) -> None:
        """
        Remove custom property *key*.

        :param key: The property key.
        """
        self._layer.removeCustomProperty(key)

    @override
    def _raw_keys(self) -> list[str]:
        """
        Return the layer's custom property keys.

        :return: The list of property keys.
        """
        return list(self._layer.customPropertyKeys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_project(project: QgsProject | None) -> QgsProject:
    """
    Return *project*, falling back to the singleton :meth:`qgis.core.QgsProject.instance`.

    :param project: An explicit project, or :data:`None` to use the singleton.
    :return: A non-:data:`None` :class:`~qgis.core.QgsProject`.
    :raise RuntimeError: If no project is available.
    """
    resolved = project if project is not None else QgsProject.instance()
    if resolved is None:
        msg = "No QgsProject available; pass project= or ensure QGIS is initialized."
        raise RuntimeError(msg)
    return resolved
