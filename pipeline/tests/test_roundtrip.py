from __future__ import annotations

from pathlib import Path

from shapely.geometry import box

from flm_pipeline.roundtrip import write_and_verify_roundtrip


def test_geopackage_roundtrip_preserves_layers_ids_crs_and_geometry(tmp_path: Path) -> None:
    result = write_and_verify_roundtrip(tmp_path / "sample.gpkg", box(-105.01, 39.74, -105.0, 39.75))
    assert set(result) == {"nodes", "lines", "polygons"}
    assert all(layer["feature_count"] == 1 for layer in result.values())
    assert all(layer["crs"] == "EPSG:4326" for layer in result.values())
    assert result["polygons"]["string_id_preserved"] is True
