"""
Plugin-agnostic library of reusable QGIS plugin helpers.

Every module here is written to be reusable by any QGIS plugin and carries no dependency on this
plugin's identity or domain logic: structured logging, typed settings and persistence proxies,
SQL/GeoPackage and zip helpers, translation support, and an env-gated ``debugpy`` bootstrap.
"""
