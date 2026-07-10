"""
The plugin's QGIS Processing framework integration.

Houses :class:`~.provider.StratifiedPackagerProvider` and the single
:class:`~.algorithm.StratifiedPackagerAlgorithm` it registers, together with the
algorithm's supporting modules: parameter resolution, strata, matching, staging,
worker threads, project building, bundling and reporting. Algorithm behavior is
normatively specified in ``SPEC.md`` at the repository root.
"""
