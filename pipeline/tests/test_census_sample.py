from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import zipfile

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

from flm_pipeline.census_sample import (
    CensusConfigError,
    CensusJoinError,
    CensusSampleError,
    CensusSampleConfig,
    CensusSource,
    _sample_worker,
    _read_selected_geometries,
    _fetch_county_acs,
    _validate_local_catalog,
    _write_geopackage,
    join_acs_to_geometries,
    load_census_config,
    validate_acs_response,
    validate_metadata,
    validate_source_geoid,
)
from flm_pipeline.census_spec import ACS_REQUEST_FIELDS, GEOGRAPHY_FIELDS, SPECIFICATION_VERSION, VARIABLES
from flm_pipeline.census_http import CensusResponse


def _config_text(accepted: str = SPECIFICATION_VERSION, block_hash: str = "a" * 64) -> str:
    return f'''config_version = "census-sample-1"
specification_version = "{SPECIFICATION_VERSION}"
accepted_specification_version = "{accepted}"
state_fips = "08"
county_fips = ["031", "073"]
output_root = "data/generated/prototype/census-samples"
cache_root = "data/generated/prototype/census-cache"

[cache]
snapshot_id = "fixture-1"

[limits]
seconds = 1200
rss_bytes = 4294967296

[metadata]
B01003_sha256 = ""
B08201_sha256 = ""

[sources.census_blocks]
path = "data/raw/blocks.zip"
expected_sha256 = "{block_hash}"

[sources.census_block_groups]
path = "data/raw/groups.zip"
expected_sha256 = "{'b' * 64}"

[sources.variables_catalog]
path = "data/raw/variables.json"
expected_sha256 = "{'c' * 64}"
'''


def _acs_payload(county: str = "031") -> list[list[str]]:
    header = ["NAME", *[f for f in ACS_REQUEST_FIELDS if f != "NAME"], *GEOGRAPHY_FIELDS]
    values = {
        "NAME": "Block Group 1, Census Tract 1, Denver County, Colorado",
        "state": "08",
        "county": county,
        "tract": "000100" if county == "031" else "900100",
        "block group": "1",
    }
    for cell in VARIABLES:
        values[f"{cell}E"] = "0" if cell == "B01003_001" else "10"
        values[f"{cell}EA"] = ""
        values[f"{cell}M"] = "2"
        values[f"{cell}MA"] = ""
    return [header, [values[name] for name in header]]


def _metadata(group: str) -> dict:
    variables = {}
    for cell, expected in VARIABLES.items():
        if not cell.startswith(group + "_"):
            continue
        for suffix in ("E", "EA", "M", "MA"):
            variables[f"{cell}{suffix}"] = {
                "concept": expected["concept"],
                "label": expected["estimate_label"] if suffix == "E" else f"fixture {suffix}",
                "predicateType": "string" if suffix in {"EA", "MA"} else "int",
            }
    return {"variables": variables}


def test_config_requires_proposal_acceptance_and_explicit_source_hashes(tmp_path: Path) -> None:
    config_path = tmp_path / "sample.toml"
    config_path.write_text(_config_text(accepted=""), encoding="utf-8")
    with pytest.raises(CensusConfigError, match="not been explicitly accepted"):
        load_census_config(config_path)

    config_path.write_text(_config_text(block_hash=""), encoding="utf-8")
    with pytest.raises(CensusConfigError, match="explicitly accepted lowercase SHA-256"):
        load_census_config(config_path)

    config_path.write_text(_config_text(), encoding="utf-8")
    config = load_census_config(config_path)
    assert config.specification_version == SPECIFICATION_VERSION
    assert config.county_fips == ("031", "073")
    assert config.sources["census_blocks"].expected_sha256 == "a" * 64


def test_config_rejects_paths_outside_repo_and_unknown_counties(tmp_path: Path) -> None:
    config_path = tmp_path / "sample.toml"
    config_path.write_text(_config_text().replace('data/raw/blocks.zip', '../outside.zip'), encoding="utf-8")
    with pytest.raises(CensusConfigError, match="stay within the repository"):
        load_census_config(config_path)

    config_path.write_text(_config_text().replace('["031", "073"]', '["031", "999"]'), encoding="utf-8")
    with pytest.raises(CensusConfigError, match="county allowlist"):
        load_census_config(config_path)

    config_path.write_text(_config_text().replace('data/raw/blocks.zip', 'data/staging/blocks.zip'), encoding="utf-8")
    with pytest.raises(CensusConfigError, match="inside data/raw"):
        load_census_config(config_path)


def test_acs_response_maps_by_header_name_and_preserves_zero_and_raw_quartets() -> None:
    payload = _acs_payload()
    payload[0] = list(reversed(payload[0]))
    payload[1] = list(reversed(payload[1]))
    result = validate_acs_response(payload, "031")
    assert len(result) == 1
    assert result[0]["geoid"] == "080310001001"
    assert result[0]["B01003_001"]["estimate"] == 0
    assert result[0]["B01003_001"]["raw_estimate"] == "0"
    assert result[0]["B08201_001"]["moe"] == 2


def test_county_request_uses_only_the_allowlisted_hierarchy_and_exact_fields(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "sample.toml"
    config_path.write_text(_config_text(), encoding="utf-8")
    config = load_census_config(config_path)
    captured = {}

    def fake_request(endpoint, parameters, cache_root, **kwargs):
        captured.update({"endpoint": endpoint, "parameters": tuple(parameters), "kwargs": kwargs})
        return CensusResponse(
            _acs_payload(), "0" * 64, 100, "cache-id", False,
            {"request": "sanitized"}, "2026-11-05T00:00:00+00:00",
        )

    monkeypatch.setattr("flm_pipeline.census_sample.request_json", fake_request)
    rows, report = _fetch_county_acs(config, "031", "local-key-value")
    assert len(rows) == 1
    assert report["returned_rows"] == 1
    assert captured["parameters"] == (
        ("get", ",".join(sorted(ACS_REQUEST_FIELDS))),
        ("for", "block group:*"),
        ("in", "state:08"),
        ("in", "county:031"),
        ("in", "tract:*"),
    )
    assert captured["kwargs"]["requires_key"] is True
    assert captured["kwargs"]["api_key"] == "local-key-value"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload[0].append("EXTRA"),
        lambda payload: payload[0].remove("NAME"),
        lambda payload: payload[1].pop(),
        lambda payload: payload[1].__setitem__(payload[0].index("county"), "073"),
        lambda payload: payload[1].__setitem__(payload[0].index("state"), "8"),
    ],
)
def test_acs_response_rejects_extra_wrong_width_and_wrong_geographies(mutate) -> None:
    payload = _acs_payload()
    mutate(payload)
    with pytest.raises((CensusSampleError, TypeError)):
        validate_acs_response(payload, "031")


def test_acs_response_rejects_duplicate_headers_geographies_and_rows() -> None:
    payload = _acs_payload()
    payload[0][1] = payload[0][0]
    with pytest.raises(CensusSampleError, match="unique"):
        validate_acs_response(payload, "031")

    duplicate = _acs_payload()
    duplicate.append(duplicate[1].copy())
    acs_rows = validate_acs_response(duplicate, "031")
    geometry = {"GEOID": "080310001001", "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])}
    with pytest.raises(CensusJoinError) as caught:
        join_acs_to_geometries([geometry], acs_rows, "031")
    assert caught.value.report["duplicate_acs_count"] == 1


@pytest.mark.parametrize("group", ["B01003", "B08201"])
def test_official_metadata_requires_expected_variables_concepts_and_labels(group: str) -> None:
    validate_metadata(group, _metadata(group))
    changed = _metadata(group)
    target = next(cell for cell in VARIABLES if cell.startswith(group + "_"))
    changed["variables"][f"{target}E"]["label"] = "wrong"
    with pytest.raises(CensusSampleError, match="label differs"):
        validate_metadata(group, changed)


def test_source_geoid_requires_string_components_and_exact_agreement() -> None:
    row = {
        "STATEFP": "08", "COUNTYFP": "031", "TRACTCE": "000100", "BLKGRPCE": "1",
        "GEOID": "080310001001",
    }
    assert validate_source_geoid("census_block_groups", row) == "080310001001"
    with pytest.raises(CensusSampleError, match="12-character"):
        validate_source_geoid("census_block_groups", {**row, "GEOID": "80310001001"})
    with pytest.raises(CensusSampleError, match="decimal string"):
        validate_source_geoid("census_block_groups", {**row, "STATEFP": 8})


def test_local_catalog_selected_fields_are_checked_without_claiming_a_vintage(tmp_path: Path) -> None:
    variables = {}
    for cell, expected in VARIABLES.items():
        variables[f"{cell}E"] = {
            "label": expected["estimate_label"],
            "concept": expected["concept"],
            "group": cell.split("_")[0],
            "predicateType": "int",
            "attributes": f"{cell}EA,{cell}M,{cell}MA",
        }
    catalog = tmp_path / "variables.json"
    catalog.write_text(json.dumps({"variables": variables}), encoding="utf-8")
    source = CensusSource("variables_catalog", catalog, "data/raw/variables.json", "0" * 64)
    assert _validate_local_catalog(source)["vintage"] == "unverified"
    variables["B01003_001E"]["label"] = "different"
    catalog.write_text(json.dumps({"variables": variables}), encoding="utf-8")
    with pytest.raises(CensusSampleError, match="disagrees"):
        _validate_local_catalog(source)


def _write_zipped_shapefile(path: Path, source_id: str) -> None:
    directory = path.parent / f"shape-{source_id}"
    directory.mkdir()
    rows = []
    for county, tract, block in (("031", "000100", "0001"), ("073", "900100", "0002")):
        if source_id == "census_blocks":
            geoid = "08" + county + tract + block
            row = {
                "STATEFP20": "08", "COUNTYFP20": county, "TRACTCE20": tract, "BLOCKCE20": block,
                "GEOID20": geoid, "NAME20": "Block", "MTFCC20": "G1010", "UR20": "R",
                "UACE20": "00000", "UATYPE20": "", "FUNCSTAT20": "S", "ALAND20": 100,
                "AWATER20": 0, "INTPTLAT20": "39.000000", "INTPTLON20": "-105.000000",
                "HOUSING20": 2, "POP20": 0,
            }
        else:
            block_group = "1"
            geoid = "08" + county + tract + block_group
            row = {
                "STATEFP": "08", "COUNTYFP": county, "TRACTCE": tract, "BLKGRPCE": block_group,
                "GEOID": geoid, "GEOIDFQ": "1500000US" + geoid, "NAMELSAD": "Block Group 1",
                "MTFCC": "G5030", "FUNCSTAT": "S", "ALAND": 100, "AWATER": 0,
                "INTPTLAT": "39.000000", "INTPTLON": "-105.000000",
            }
        row["geometry"] = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        rows.append(row)
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4269")
    shapefile = directory / f"{source_id}.shp"
    frame.to_file(shapefile, driver="ESRI Shapefile", encoding="UTF-8")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in directory.iterdir():
            archive.write(item, arcname=item.name)


@pytest.mark.parametrize("source_id", ["census_blocks", "census_block_groups"])
def test_full_selected_archive_read_preserves_string_geoids_and_crs(tmp_path: Path, source_id: str) -> None:
    path = tmp_path / f"{source_id}.zip"
    _write_zipped_shapefile(path, source_id)
    source = CensusSource(source_id, path, path.name, "0" * 64)
    rows, crs, report = _read_selected_geometries(source)
    assert len(rows) == 2
    assert crs == "EPSG:4269"
    assert report["invalid_geometry_count"] == 0
    assert all(isinstance(row["GEOID20" if source_id == "census_blocks" else "GEOID"], str) for row in rows)
    if source_id == "census_blocks":
        assert all(row["POP20"] == 0 for row in rows)
        assert {row["COUNTYFP20"] for row in rows} == {"031", "073"}
    else:
        assert {row["COUNTYFP"] for row in rows} == {"031", "073"}


def test_complete_join_reports_both_unmatched_sides_and_never_inner_joins() -> None:
    geometry_rows = [{"GEOID": "080310001001", "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])}]
    acs_rows = [{"geoid": "080310002001", "NAME": "BG", "county_fips": "031"}]
    with pytest.raises(CensusJoinError) as caught:
        join_acs_to_geometries(geometry_rows, acs_rows, "031")
    assert caught.value.report["unmatched_geometry_examples"] == ["080310001001"]
    assert caught.value.report["unmatched_acs_examples"] == ["080310002001"]
    assert caught.value.report["join_cardinality"] == "incomplete"


def test_duplicate_keys_on_both_join_sides_are_reported() -> None:
    geometry = {"GEOID": "080310001001", "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])}
    acs = {"geoid": "080310001001", "NAME": "BG", "county_fips": "031"}
    with pytest.raises(CensusJoinError) as caught:
        join_acs_to_geometries([geometry, geometry], [acs, acs], "031")
    assert caught.value.report["duplicate_geometry_count"] == 1
    assert caught.value.report["duplicate_acs_count"] == 1


def test_reopened_geopackages_reconcile_ids_geometry_and_quartet_attributes(tmp_path: Path) -> None:
    geometry = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    blocks = [{
        "GEOID20": "080310001000001", "STATEFP20": "08", "COUNTYFP20": "031",
        "POP20": 0, "HOUSING20": 4, "geometry": geometry,
    }]
    block_report = _write_geopackage(tmp_path / "blocks.gpkg", blocks, "EPSG:4269", False, "census_blocks")
    assert block_report["identifier_count"] == 1

    acs = {
        "geoid": "080310001001", "NAME": "Block Group 1", "county_fips": "031",
        "B01003_001": {
            "raw_estimate": "0", "raw_estimate_annotation": "", "raw_moe": "2", "raw_moe_annotation": "",
            "estimate": 0, "estimate_status": "valid", "estimate_annotation": None,
            "moe": 2, "moe_status": "valid", "moe_annotation": None,
        },
    }
    groups = [{"GEOID": acs["geoid"], "STATEFP": "08", "COUNTYFP": "031", "geometry": geometry, "acs": acs}]
    group_report = _write_geopackage(tmp_path / "groups.gpkg", groups, "EPSG:4269", True, "census_block_groups")
    assert group_report["attributes_reconciled"]
    assert group_report["geometries_reopened_and_matched"]


def test_synthetic_worker_completes_two_counties_without_network_or_cross_vintage_join(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[2]
    blocks_path = tmp_path / "blocks.zip"
    groups_path = tmp_path / "groups.zip"
    _write_zipped_shapefile(blocks_path, "census_blocks")
    _write_zipped_shapefile(groups_path, "census_block_groups")
    catalog_path = tmp_path / "variables.json"
    catalog_variables = {}
    for cell, expected in VARIABLES.items():
        catalog_variables[f"{cell}E"] = {
            "label": expected["estimate_label"],
            "concept": expected["concept"],
            "group": cell.split("_")[0],
            "predicateType": "int",
            "attributes": f"{cell}EA,{cell}M,{cell}MA",
        }
    catalog_path.write_text(json.dumps({"variables": catalog_variables}), encoding="utf-8")
    config_path = tmp_path / "synthetic-config.toml"
    config_path.write_text("synthetic local config identity\n", encoding="utf-8")
    source_specs = {
        "census_blocks": blocks_path,
        "census_block_groups": groups_path,
        "variables_catalog": catalog_path,
    }
    sources = {
        source_id: CensusSource(
            source_id, path, path.name, hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for source_id, path in source_specs.items()
    }
    config = CensusSampleConfig(
        config_path=config_path,
        repo_root=root,
        configuration_version="census-sample-1",
        specification_version=SPECIFICATION_VERSION,
        accepted_specification_version=SPECIFICATION_VERSION,
        state_fips="08",
        county_fips=("031", "073"),
        sources=sources,
        output_root=root / "data" / "generated" / "prototype" / "census-samples",
        output_relative_path="data/generated/prototype/census-samples",
        cache_root=tmp_path / "cache",
        cache_relative_path="data/generated/prototype/census-cache",
        cache_snapshot_id="synthetic-1",
        timeout_seconds=1200,
        rss_limit_bytes=4 * 1024**3,
        expected_metadata_sha256={"B01003": None, "B08201": None},
    )
    stage = tmp_path / "worker-stage"
    stage.mkdir()
    (stage / "worker.log").write_text("", encoding="utf-8")
    monkeypatch.setenv("CENSUS_API_KEY", "synthetic-test-key")

    def fake_request(endpoint, parameters, cache_root, **kwargs):
        if "/groups/" in endpoint:
            value = _metadata("B01003" if "B01003" in endpoint else "B08201")
        else:
            county = next(value.split(":", 1)[1] for name, value in parameters if name == "in" and value.startswith("county:"))
            value = _acs_payload(county)
        body = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return CensusResponse(
            value, hashlib.sha256(body).hexdigest(), len(body), hashlib.sha256(endpoint.encode()).hexdigest(),
            False, {"host": "api.census.gov", "path": endpoint, "parameters": list(parameters)},
            datetime.now(UTC).isoformat(),
        )

    monkeypatch.setattr("flm_pipeline.census_sample.request_json", fake_request)
    result = _sample_worker(config, stage, "synthetic-two-county")
    assert result["status"] == "complete"
    assert result["checks"]["complete_one_to_one_joins"]
    assert result["joins"]["031"]["geometry_rows"] == 1
    assert result["joins"]["073"]["acs_rows"] == 1
    assert result["source_totals_by_county"]["031"]["decennial_2020_block_counts"]["POP20"] == 0
    assert result["source_totals_by_county"]["031"]["comparison_between_vintages"] == "not_performed"
    assert (stage / "blocks-2020.gpkg").is_file()
    assert (stage / "block-groups-2024-acs.gpkg").is_file()
    assert (stage / "block-groups-2024-acs.jsonl").is_file()



def test_request_fields_match_accepted_literal_api_names():
    assert ACS_REQUEST_FIELDS == (
        "NAME", "B01003_001E", "B01003_001EA", "B01003_001M", "B01003_001MA",
        "B08201_001E", "B08201_001EA", "B08201_001M", "B08201_001MA",
        "B08201_002E", "B08201_002EA", "B08201_002M", "B08201_002MA",
    )
