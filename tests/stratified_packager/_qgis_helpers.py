"""Shared QGIS/GDAL test helpers (imported only after the relevant importorskip guard)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from qgis.core import QgsRelationManager, QgsVectorLayer


def add_relation(
    relation_id: str,
    referencing: QgsVectorLayer,
    referenced: QgsVectorLayer,
    field_pairs: list[tuple[str, str]],
) -> None:
    """
    Register one relation on the live project's relation manager.

    :param relation_id: Relation id (doubles as its name).
    :param referencing: Child layer.
    :param referenced: Parent layer.
    :param field_pairs: Ordered ``(referencing field, referenced field)`` pairs.
    """
    # Imported lazily so the qgis-free test modules can import this module's
    # GDAL helpers without a qgis installation.
    from qgis.core import QgsRelation  # noqa: PLC0415

    manager = relation_manager()
    relation = QgsRelation()
    relation.setId(relation_id)
    relation.setName(relation_id)
    relation.setReferencingLayer(referencing.id())
    relation.setReferencedLayer(referenced.id())
    for referencing_field, referenced_field in field_pairs:
        relation.addFieldPair(referencing_field, referenced_field)
    assert relation.isValid(), relation_id  # test helper
    manager.addRelation(relation)


def relation_manager() -> QgsRelationManager:
    """
    Return the live project's relation manager.

    :return: The manager (assertions guard the Optionals for type checkers).
    """
    # Imported lazily so the qgis-free test modules can import this module's
    # GDAL helpers without a qgis installation.
    from qgis.core import QgsProject  # noqa: PLC0415

    project = QgsProject.instance()
    assert project is not None
    manager = project.relationManager()
    assert manager is not None
    return manager


def build_alpha_gpkg(path: Path) -> Path:
    """
    Build a GeoPackage with one point layer ``alpha`` (fields ``a``, ``b``), six rows.

    :param path: Destination gpkg path.
    :return: *path*.
    """
    # Imported lazily so qgis-free callers do not need this module's qgis imports.
    from osgeo import ogr, osr  # noqa: PLC0415

    ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    layer = ds.CreateLayer("alpha", srs, ogr.wkbPoint)
    layer.CreateField(ogr.FieldDefn("a", ogr.OFTInteger))
    layer.CreateField(ogr.FieldDefn("b", ogr.OFTString))
    defn = layer.GetLayerDefn()
    for index in range(6):
        feature = ogr.Feature(defn)
        feature.SetField("a", index)
        feature.SetField("b", f"row{index}")
        point = ogr.Geometry(ogr.wkbPoint)
        point.AddPoint_2D(float(index), 0.0)
        feature.SetGeometry(point)
        layer.CreateFeature(feature)
    del layer
    del ds
    return path
