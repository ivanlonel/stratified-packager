"""
QGIS-free foundation for the typed key/value proxies: conversions, mapping base, environment.

This module holds the parts of the persistence layer that touch no QGIS objects, so it is
importable (and thread-safe) without a QGIS runtime:

* a small **type-conversion registry** (:func:`register_converter`, :func:`to_storage`,
  :func:`from_storage`) that round-trips Python values to and from the scalar
  representations every backend can persist;
* :class:`MappingProxy`, the abstract :class:`~collections.abc.MutableMapping` base that the
  concrete proxies subclass, providing consistent ``[]``/``in``/``len``/iteration semantics
  plus a typed :meth:`~MappingProxy.get`; and
* :class:`EnvironmentVariables` + the :class:`EnvVar` descriptors — a concrete
  :class:`MappingProxy` over :data:`os.environ`.

The conversion registry here covers the stdlib types (:class:`str`, :class:`int`,
:class:`float`, :class:`bool`, ``list[str]``, :class:`pathlib.Path`,
:class:`datetime.datetime`, :class:`datetime.date`) and any :class:`enum.Enum`. QGIS-only
types (e.g. :class:`~qgis.PyQt.QtGui.QColor`) are registered by the modules that own them —
see :mod:`~.toolbelt.settings`, which also adds the QGIS-backed proxies
(``QgsSettings``, ``QgsProject``, layer properties) on top of this base.

Dict-like and typed-descriptor access mirror how a typed entry sits over a flat store::

    env = EnvironmentVariables()
    env["MY_FLAG"] = True  # stored as the string "True"
    env.get("MY_PORT", 5678, cast=int)  # -> int, with a default


    class DebugEnv(EnvironmentVariables):
        QGIS_DEBUGPY = BoolEnvVar(default=False)
        QGIS_DEBUGPY_PORT = IntEnvVar(default=5678)


    DebugEnv().QGIS_DEBUGPY  # -> bool
"""

from __future__ import annotations

import os
from abc import abstractmethod
from collections.abc import Iterable, Mapping, MutableMapping
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, TypeGuard, overload, override

from .utils import coerce_bool

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


__all__: list[str] = [
    "BoolEnvVar",
    "EnvVar",
    "EnvironmentVariables",
    "FloatEnvVar",
    "IntEnvVar",
    "MappingProxy",
    "PathEnvVar",
    "StorableValue",
    "StrEnvVar",
    "TypeConverter",
    "from_storage",
    "register_converter",
    "to_storage",
]

type StorableValue = str | int | float | bool | list[str]
"""Union of representations every backend can persist natively."""


# ---------------------------------------------------------------------------
# Conversion registry
# ---------------------------------------------------------------------------


class TypeConverter[T]:
    """
    Round-trips a single Python type to and from a backend-storable representation.

    Instances are registered with :func:`register_converter` and looked up by
    :func:`to_storage` and :func:`from_storage`.
    """

    def __init__(
        self,
        serialize: Callable[[T], StorableValue],
        deserialize: Callable[[object], T],
    ) -> None:
        """
        Store the two conversion callables.

        :param serialize: Callable turning a ``T`` into a :data:`StorableValue`.
        :param deserialize: Callable rebuilding a ``T`` from a stored value (which
            may have been read back as a different type, e.g. a :class:`bool`
            persisted as the string ``"true"``).
        """
        self.serialize: Final[Callable[[T], StorableValue]] = serialize
        self.deserialize: Final[Callable[[object], T]] = deserialize


_CONVERTERS: Final[dict[type, TypeConverter[Any]]] = {}
"""Registry mapping each Python type to its :class:`TypeConverter`."""


def register_converter[T](
    py_type: type[T],
    serialize: Callable[[T], StorableValue],
    deserialize: Callable[[object], T],
) -> None:
    """
    Register conversion callables for *py_type*, replacing any existing entry.

    :param py_type: The Python type the converter handles.
    :param serialize: Callable turning a *py_type* value into a storable value.
    :param deserialize: Callable rebuilding a *py_type* value from a stored value.
    """
    _CONVERTERS[py_type] = TypeConverter(serialize, deserialize)


def _as_str(raw: object) -> str:
    """
    Coerce a stored value to :class:`str`.

    :param raw: The stored value.
    :return: *raw* if already a string, otherwise ``str(raw)``.
    """
    return raw if isinstance(raw, str) else str(raw)


def _as_int(raw: object) -> int:
    """
    Coerce a stored value to :class:`int`.

    :param raw: The stored value.
    :return: The integer value (numbers are truncated; strings are parsed).
    """
    if isinstance(raw, (int, float)):
        return int(raw)
    return int(str(raw))


def _as_float(raw: object) -> float:
    """
    Coerce a stored value to :class:`float`.

    :param raw: The stored value.
    :return: The floating-point value.
    """
    if isinstance(raw, (int, float)):
        return float(raw)
    return float(str(raw))


def _is_item_iterable(value: object) -> TypeGuard[Iterable[object]]:
    """
    Return whether *value* should be treated as a sequence of stringifiable items.

    True for any :class:`~collections.abc.Iterable` except strings, bytes, and
    mappings: a string is stored whole (never exploded into characters), bytes are
    stored whole, and a mapping is not silently reduced to its keys.

    :param value: The value to classify.
    :return: :data:`True` if *value* is a non-string, non-mapping iterable.
    """
    return isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray, Mapping))


def _to_str_list(raw: object) -> list[str]:
    """
    Coerce a stored value into a list of strings.

    :param raw: The stored value (any non-string iterable, or a scalar).
    :return: A list of strings; a non-string iterable is stringified item by item,
        a scalar becomes a single-element list, and an empty or :data:`None` value
        becomes an empty list.
    """
    if _is_item_iterable(raw):
        return [str(item) for item in raw]
    if raw in (None, ""):
        return []
    return [str(raw)]


register_converter(str, _as_str, _as_str)
register_converter(int, _as_int, _as_int)
register_converter(float, _as_float, _as_float)
register_converter(bool, coerce_bool, coerce_bool)
register_converter(list, _to_str_list, _to_str_list)
register_converter(Path, _as_str, lambda r: Path(str(r)))
register_converter(datetime, lambda d: d.isoformat(), lambda r: datetime.fromisoformat(str(r)))
register_converter(date, lambda d: d.isoformat(), lambda r: date.fromisoformat(str(r)))


def _find_converter(klass: type) -> TypeConverter[Any] | None:
    """
    Return the converter registered for *klass* or its nearest registered base.

    Walking the MRO lets a converter registered for an abstract base (e.g.
    :class:`pathlib.Path`) handle the concrete instances QGIS hands back (e.g.
    :class:`pathlib.PosixPath` / :class:`pathlib.WindowsPath`).

    :param klass: The type to resolve a converter for.
    :return: The matching :class:`TypeConverter`, or :data:`None` if none is registered.
    """
    for base in klass.__mro__:
        converter = _CONVERTERS.get(base)
        if converter is not None:
            return converter
    return None


def to_storage(value: object) -> object:
    """
    Convert a Python *value* into a representation a QGIS backend can persist.

    :class:`enum.Enum` members are reduced to their ``value``; otherwise the
    converter registered for the value's type (or nearest registered base) is
    used. Values whose type has no converter are returned unchanged (assumed
    natively storable).

    :param value: The Python value to convert.
    :return: A backend-storable representation of *value*.
    """
    if isinstance(value, Enum):
        return value.value
    converter = _find_converter(type(value))
    return converter.serialize(value) if converter is not None else value


def from_storage[T](raw: object, target_type: type[T]) -> T:
    """
    Rebuild a value of *target_type* from a stored representation.

    :class:`enum.Enum` subclasses are reconstructed by value lookup
    (``target_type(raw)``); every other type must have a converter registered for
    it or a base, whose ``deserialize`` callable is then applied.

    :param raw: The stored value, possibly read back as a different type.
    :param target_type: The desired Python type.
    :return: *raw* converted to *target_type*.
    :raise TypeError: If no converter is registered for *target_type*.
    :raise ValueError: If the registered converter cannot parse *raw* (e.g. a non-numeric string).
    """
    if issubclass(target_type, Enum):
        return target_type(raw)
    converter = _find_converter(target_type)
    if converter is None:
        msg = f"No converter registered for {target_type!r}; add one via register_converter()."
        raise TypeError(msg)
    result: T = converter.deserialize(raw)
    return result


# ---------------------------------------------------------------------------
# Mapping proxy base
# ---------------------------------------------------------------------------


class MappingProxy(MutableMapping[str, object]):
    """
    Common :class:`~collections.abc.MutableMapping` plumbing for the proxies.

    Subclasses implement four hooks — :meth:`_raw_get`, :meth:`_raw_set`,
    :meth:`_raw_del`, and :meth:`_raw_keys` — and inherit consistent
    ``[]``/``in``/``len``/iteration semantics plus a typed :meth:`get`. The
    typed-read routing lives in :meth:`_typed_get`, which backends with
    type-specific read APIs may override.
    """

    @abstractmethod
    def _raw_get(self, key: str) -> tuple[object, bool]:
        """
        Read *key* from the backend.

        :param key: The lookup key.
        :return: A ``(value, present)`` pair; *value* is unspecified when
            *present* is :data:`False`.
        """

    @abstractmethod
    def _raw_set(self, key: str, value: object) -> None:
        """
        Write *value* at *key* (already converted via :func:`to_storage`).

        :param key: The destination key.
        :param value: The storable value.
        """

    @abstractmethod
    def _raw_del(self, key: str) -> None:
        """
        Delete *key* from the backend (only called when the key is present).

        :param key: The key to remove.
        """

    @abstractmethod
    def _raw_keys(self) -> list[str]:
        """
        Return the keys exposed by this proxy.

        :return: The list of keys for iteration and length.
        """

    def _typed_get(self, key: str, cast: type[object] | None) -> tuple[object, bool]:
        """
        Read *key* and convert it to *cast* when present.

        The default uses :meth:`_raw_get` plus :func:`from_storage`; backends with
        type-specific read APIs override this.

        :param key: The lookup key.
        :param cast: Target Python type, or :data:`None` for the raw value.
        :return: A ``(value, present)`` pair.
        """
        value, present = self._raw_get(key)
        if not present:
            return None, False
        return (value if cast is None else from_storage(value, cast)), True

    @override
    def __getitem__(self, key: str) -> object:
        """
        Return the raw stored value for *key*.

        :param key: The lookup key.
        :return: The stored value.
        :raise KeyError: If *key* is not present.
        """
        value, present = self._raw_get(key)
        if not present:
            raise KeyError(key)
        return value

    @override
    def __setitem__(self, key: str, value: object) -> None:
        """
        Store *value* at *key*, converting it via :func:`to_storage`.

        :param key: The destination key.
        :param value: The value to store.
        """
        self._raw_set(key, to_storage(value))

    @override
    def __delitem__(self, key: str) -> None:
        """
        Delete *key*.

        :param key: The key to remove.
        :raise KeyError: If *key* is not present.
        """
        if not self._raw_get(key)[1]:
            raise KeyError(key)
        self._raw_del(key)

    @override
    def __iter__(self) -> Iterator[str]:
        """
        Iterate over the proxy's keys.

        :return: An iterator over the keys.
        """
        return iter(self._raw_keys())

    @override
    def __len__(self) -> int:
        """
        Return the number of keys.

        :return: The key count.
        """
        return len(self._raw_keys())

    @override
    def __contains__(self, key: object) -> bool:
        """
        Report whether *key* is present.

        :param key: The candidate key.
        :return: :data:`True` if *key* is a present string key.
        """
        return isinstance(key, str) and self._raw_get(key)[1]

    # get() intentionally widens Mapping.get with an optional keyword-only cast=.
    # pylint: disable=arguments-differ,signature-differs
    @overload
    def get(self, key: str, /) -> object | None: ...

    @overload
    def get(self, key: str, default: object) -> object: ...

    @overload
    def get[T](self, key: str, default: T | None = ..., *, cast: type[T]) -> T | None: ...

    @override
    def get(  # ty: ignore[invalid-method-override]
        self, key: str, default: object = None, *, cast: type[object] | None = None
    ) -> object:
        """
        Return the value for *key*, optionally converted to *cast*.

        :param key: The lookup key.
        :param default: Value returned when *key* is absent.
        :param cast: Target Python type; when given, the stored value is converted
            (via the backend's typed read or :func:`from_storage`).
        :return: The (optionally converted) value, or *default* when absent.
        """
        value, present = self._typed_get(key, cast)
        return value if present else default


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------


class EnvironmentVariables(MappingProxy):
    """
    Dict-like proxy over the process environment (:data:`os.environ`).

    Reads and writes environment variables through the shared converter registry, so
    callers get typed access without hand-rolling string parsing::

        env = EnvironmentVariables()
        env.get("MY_PORT", 5678, cast=int)  # -> int, with a default
        env["MY_FLAG"] = True  # stored as the string "True"

    Subclass it and declare :class:`EnvVar` descriptors for a typed, self-documenting
    schema — ``self.<NAME>`` returns the typed value (its default when unset) and
    ``self.<NAME> = value`` writes it, while the instance stays a full dict-like proxy
    for any other variable::

        class DebugEnv(EnvironmentVariables):
            QGIS_DEBUGPY = BoolEnvVar(default=False)
            QGIS_DEBUGPY_PORT = IntEnvVar(default=5678)


        env = DebugEnv()
        env.QGIS_DEBUGPY  # -> bool
        env.QGIS_DEBUGPY_PORT  # -> int

    It touches no QGIS objects, so it is usable from any thread; writes do, however,
    mutate process-global state. The environment stores only strings, so scalar types
    (:class:`bool`, :class:`int`, :class:`float`, :class:`str`, :class:`~pathlib.Path`)
    round-trip, while structured values are stored as their :class:`str` form and do not.
    """

    def __init__(self, environ: MutableMapping[str, str] | None = None) -> None:
        """
        Initialize the proxy.

        :param environ: Backing environment mapping; defaults to :data:`os.environ`.
        """
        self._environ: MutableMapping[str, str] = environ if environ is not None else os.environ

    @override
    def _raw_get(self, key: str) -> tuple[object, bool]:
        """
        Read environment variable *key*.

        :param key: The variable name.
        :return: A ``(value, present)`` pair.
        """
        if key not in self._environ:
            return None, False
        return self._environ[key], True

    @override
    def _raw_set(self, key: str, value: object) -> None:
        """
        Set environment variable *key* to the string form of *value*.

        :param key: The variable name.
        :param value: The storable value; coerced to :class:`str` because the environment
            holds only strings.
        """
        self._environ[key] = str(value)

    @override
    def _raw_del(self, key: str) -> None:
        """
        Unset environment variable *key*.

        :param key: The variable name.
        """
        del self._environ[key]

    @override
    def _raw_keys(self) -> list[str]:
        """
        Return the defined environment variable names.

        :return: The list of variable names.
        """
        return list(self._environ)


class EnvVar[T]:
    """
    Descriptor mapping a class attribute to a typed environment variable.

    Declare instances as class attributes of an :class:`EnvironmentVariables` subclass; the
    attribute name is used as the variable name unless *key* overrides it. Reads and
    writes route through the owning :class:`EnvironmentVariables` proxy (hence the
    converter registry), so ``schema.NAME`` and ``schema["NAME"]`` address the same
    variable — the former typed and defaulted.

    Concrete subclasses (:class:`BoolEnvVar` and siblings) bind ``T`` by forwarding the
    target type to ``__init__``.
    """

    def __init__(
        self, cast: type[T], default: T, description: str = "", *, key: str | None = None
    ) -> None:
        """
        Initialize the descriptor.

        :param cast: Target Python type the stored string is converted to on read.
        :param default: Value returned when the variable is unset.
        :param description: Human-readable description (documentation only).
        :param key: Variable name; defaults to the attribute name the descriptor is assigned to.
        """
        self._cast: type[T] = cast
        self._default: T = default
        self._description: str = description
        self._explicit_key: str | None = key
        self._name: str = ""

    def __set_name__(self, owner: type, name: str) -> None:
        """
        Capture the attribute name to use as the default variable name.

        :param owner: The class the descriptor is assigned to.
        :param name: The attribute name the descriptor is bound to.
        """
        self._name = name

    @property
    def key(self) -> str:
        """
        Environment variable name (the explicit key, or the attribute name).

        :return: The variable name this descriptor reads and writes.
        """
        return self._explicit_key if self._explicit_key is not None else self._name

    @overload
    def __get__(self, instance: None, owner: type) -> EnvVar[T]: ...

    @overload
    def __get__(self, instance: EnvironmentVariables, owner: type) -> T: ...

    def __get__(self, instance: EnvironmentVariables | None, owner: type) -> EnvVar[T] | T:
        """
        Return the descriptor on class access, or the typed value on instance access.

        :param instance: The owning proxy instance, or :data:`None` for class access.
        :param owner: The owning class.
        :return: ``self`` for class access, otherwise the converted value (the default
            when the variable is unset).
        """
        if instance is None:
            return self
        value = instance.get(self.key, self._default, cast=self._cast)
        # get() widens to T | None for the absent case, but a non-None default is always
        # supplied here, so the result is a T; fall back to the default defensively.
        return value if value is not None else self._default

    def __set__(self, instance: EnvironmentVariables, value: T) -> None:
        """
        Write *value* to the environment variable.

        :param instance: The owning proxy instance.
        :param value: The value to store; converted to its string form on write.
        """
        instance[self.key] = value

    def reset(self, instance: EnvironmentVariables) -> None:
        """
        Unset the variable so its default applies again.

        :param instance: The owning proxy instance.
        """
        instance.pop(self.key, None)


class BoolEnvVar(EnvVar[bool]):
    """A :class:`bool` environment variable, parsed via the converter registry."""

    def __init__(self, *, default: bool, description: str = "", key: str | None = None) -> None:
        """
        Initialize the descriptor.

        :param default: Value returned when the variable is unset.
        :param description: Human-readable description (documentation only).
        :param key: Variable name; defaults to the attribute name.
        """
        super().__init__(bool, default, description, key=key)


class StrEnvVar(EnvVar[str]):
    """A :class:`str` environment variable."""

    def __init__(self, *, default: str, description: str = "", key: str | None = None) -> None:
        """
        Initialize the descriptor.

        :param default: Value returned when the variable is unset.
        :param description: Human-readable description (documentation only).
        :param key: Variable name; defaults to the attribute name.
        """
        super().__init__(str, default, description, key=key)


class IntEnvVar(EnvVar[int]):
    """An :class:`int` environment variable."""

    def __init__(self, *, default: int, description: str = "", key: str | None = None) -> None:
        """
        Initialize the descriptor.

        :param default: Value returned when the variable is unset.
        :param description: Human-readable description (documentation only).
        :param key: Variable name; defaults to the attribute name.
        """
        super().__init__(int, default, description, key=key)


class FloatEnvVar(EnvVar[float]):
    """A :class:`float` environment variable."""

    def __init__(self, *, default: float, description: str = "", key: str | None = None) -> None:
        """
        Initialize the descriptor.

        :param default: Value returned when the variable is unset.
        :param description: Human-readable description (documentation only).
        :param key: Variable name; defaults to the attribute name.
        """
        super().__init__(float, default, description, key=key)


class PathEnvVar(EnvVar[Path]):
    """A :class:`~pathlib.Path` environment variable."""

    def __init__(self, *, default: Path, description: str = "", key: str | None = None) -> None:
        """
        Initialize the descriptor.

        :param default: Value returned when the variable is unset.
        :param description: Human-readable description (documentation only).
        :param key: Variable name; defaults to the attribute name.
        """
        super().__init__(Path, default, description, key=key)
