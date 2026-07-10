"""
Shared sample types for the mapping-proxy and settings test suites.

Both :mod:`tests.stratified_packager.toolbelt.test_mapping_proxy` and
:mod:`tests.stratified_packager.toolbelt.test_settings` exercise the same converter registry
and descriptor machinery, so the sample enums and the pure-function Hypothesis preset live
here rather than being duplicated in each module.
"""

from __future__ import annotations

from enum import IntEnum, IntFlag

import hypothesis

PURE_PROPERTY = hypothesis.settings(
    suppress_health_check=[hypothesis.HealthCheck.function_scoped_fixture]
)
"""Hypothesis preset for property tests over pure helpers (no per-example fixture reset)."""


class Speed(IntEnum):
    """Sample :class:`enum.IntEnum` for enum round-trip and :class:`EnumSetting` tests."""

    SLOW = 1
    FAST = 2


class Perm(IntFlag):
    """Sample :class:`enum.IntFlag` to exercise combined-flag round-tripping."""

    READ = 1
    WRITE = 2
