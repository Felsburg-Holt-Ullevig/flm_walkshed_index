from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from flm_pipeline.classification import ClassificationError, _candidate_record, run_classification
from flm_pipeline.pedestrian_config import PedestrianConfigError, load_pedestrian_settings
from flm_pipeline.pedestrian_policy import evaluate_node, evaluate_way


ROOT = Path(__file__).resolve().parents[2]
POLICY_CONFIG = ROOT / "pipeline" / "config" / "pedestrian-policy.example.toml"


def _canonical_line(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def _write_source_file(path: Path, rows: list[dict]) -> dict:
    payload = b"".join(_canonical_line(row) for row in rows)
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    return {"path": path.name, "count": len(rows), "bytes": len(payload), "sha256": digest, "semantic_sha256": digest}


def _fixture_extraction(root: Path) -> Path:
    directory = root / "extraction"
    directory.mkdir()
    nodes = [
        {"osm_id": "1", "lon": -105.0, "lat": 39.7, "tags": {}},
        {"osm_id": "2", "lon": -105.001, "lat": 39.701, "tags": {"barrier": "gate"}},
        {"osm_id": "3", "lon": -105.002, "lat": 39.702, "tags": {"foot": "no"}},
    ]
    ways = [
        {"osm_id": "100", "node_refs": ["1", "2", "3"], "tags": {"highway": "residential"}},
        {"osm_id": "101", "node_refs": ["1", "1"], "tags": {"highway": "residential"}},
        {"osm_id": "102", "node_refs": ["1", "3"], "tags": {"highway": "cycleway", "foot": "yes"}},
        {"osm_id": "103", "node_refs": ["1", "2"], "tags": {"highway": "residential", "access:conditional": "no @ (Mo-Fr)"}},
    ]
    relations = [
        {"osm_id": "200", "members": [], "tags": {"type": "restriction", "restriction:conditional": "no_left_turn @ (Mo-Fr)"}},
    ]
    files = {
        "nodes.jsonl": _write_source_file(directory / "nodes.jsonl", nodes),
        "ways.jsonl": _write_source_file(directory / "ways.jsonl", ways),
        "relations.jsonl": _write_source_file(directory / "relations.jsonl", relations),
    }
    metadata = {
        "status": "pass",
        "contract_version": "source-network-1",
        "run_id": "synthetic-source-1",
        "selection_id": "highway-node-in-bbox-complete-way-1",
        "files": files,
        "counts": {
            "emitted_nodes": 3,
            "selected_ways": 4,
            "emitted_relations": 1,
            "unique_required_way_nodes": 3,
            "complete_way_node_reference_total": 9,
            "unresolved_way_node_references": 0,
        },
        "source": {"path": "data/raw/synthetic.osm.pbf", "sha256": "a" * 64},
        "coverage": {"extract_bbox": [-105.1, 39.6, -104.9, 39.8]},
    }
    metadata_path = directory / "extraction.json"
    metadata_path.write_bytes(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
    report = {
        "report_version": "prototype-run-1",
        "status": "pass",
        "checks": {
            "inventory_linked": True,
            "source_hash_before_and_after": True,
            "entity_counts_reconciled": True,
            "required_way_references_resolve": True,
            "canonical_outputs_reopened": True,
            "worker_exit_zero": True,
            "child_cleanup_complete": True,
        },
        "output_hashes": {name: item["sha256"] for name, item in files.items()},
    }
    report["output_hashes"]["extraction.json"] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    (directory / "run-report.json").write_text(json.dumps(report, sort_keys=True), encoding="utf-8")
    return directory


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_accepted_experimental_policy_settings_are_loaded() -> None:
    settings = load_pedestrian_settings(POLICY_CONFIG)
    assert settings.rule_version == "pedestrian-policy-0.3"
    assert settings.scenario_id == "public-walk-experiment-0.3"
    assert settings.length_unit == "international_foot"
    assert settings.speed_mph == 4500 / 1609.344
    assert len(settings.config_sha256) == 64


def test_policy_config_rejects_units_that_conflict_with_acceptance(tmp_path: Path) -> None:
    text = POLICY_CONFIG.read_text(encoding="utf-8").replace('length_unit = "international_foot"', 'length_unit = "meter"')
    invalid = tmp_path / "metric.toml"
    invalid.write_text(text, encoding="utf-8")
    with pytest.raises(PedestrianConfigError, match="length_unit"):
        load_pedestrian_settings(invalid)


def test_current_loader_rejects_archived_policy_version():
    with pytest.raises(PedestrianConfigError, match="rule_version"):
        load_pedestrian_settings(ROOT / "pipeline/config/pedestrian-policy-0.2.toml")


def test_audit_outputs_reconcile_and_keep_unknown_excluded_and_conditional_records(tmp_path: Path) -> None:
    extraction = _fixture_extraction(tmp_path)
    code, result = run_classification(extraction, POLICY_CONFIG, tmp_path / "out", staging_root=tmp_path / "staging")
    assert code == 0
    assert result["status"] == "classification_complete_with_unknowns"
    assert result["coverage"]["analytical_promotion"] == "blocked_by_unknown_policy"
    output = ROOT / result["output_directory"]
    ways = _read_jsonl(output / "ways-classified.jsonl")
    nodes = _read_jsonl(output / "nodes-classified.jsonl")
    candidates = _read_jsonl(output / "candidates-classified.jsonl")
    conditional = _read_jsonl(output / "conditional-tags.jsonl")
    assert [item["evaluation"]["eligibility"] for item in ways] == ["include", "include", "include", "unknown"]
    assert {item["evaluation"]["disposition"] for item in nodes} == {"pass", "unknown", "block"}
    assert [item["eligibility"] for item in candidates] == ["unknown", "exclude", "exclude", "exclude", "unknown"]
    assert all(item["geometry_check"] == "not_run" and item["routing_ready"] is False for item in candidates)
    assert candidates[2]["same_endpoint_id"] is True
    assert "G_ZERO_LENGTH" in candidates[2]["reason_codes"]
    assert {item["entity_type"] for item in conditional} == {"way", "relation"}
    report = json.loads((output / "run-report.json").read_text(encoding="utf-8"))
    assert report["counts"]["input_ways"] == 4
    assert report["counts"]["unique_referenced_nodes"] == 3
    assert report["counts"]["ordered_pair_candidates"] == 5
    assert report["counts"]["candidates_by_policy_eligibility"] == {"exclude": 3, "unknown": 2}
    assert report["policy"]["geometry_checks"] == "not_run"
    assert report["checks"]["source_references_resolved"] is True
    tables = json.loads((output / "audit-tables.json").read_text(encoding="utf-8"))
    assert tables["ways_by_eligibility"] == {"include": 3, "unknown": 1}
    assert (output / "counts-by-highway.csv").is_file()
    assert (output / "counts-by-sidewalk-evidence.csv").is_file()
    assert (output / "conditional-tag-counts.csv").is_file()
    assert "ways-classified.jsonl" in report["output_files"]
    assert report["output_files"]["ways-classified.jsonl"]["sha256"]


def test_input_hash_mismatch_is_rejected_before_classification(tmp_path: Path) -> None:
    extraction = _fixture_extraction(tmp_path)
    with (extraction / "ways.jsonl").open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ClassificationError, match="hash does not match"):
        run_classification(extraction, POLICY_CONFIG, tmp_path / "out", staging_root=tmp_path / "staging")


def test_unknown_extraction_is_not_accepted_as_a_classifier_input(tmp_path: Path) -> None:
    extraction = _fixture_extraction(tmp_path)
    metadata_path = extraction / "extraction.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["status"] = "empty"
    metadata_path.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    with pytest.raises(ClassificationError, match="passing source-network"):
        run_classification(extraction, POLICY_CONFIG, tmp_path / "out", staging_root=tmp_path / "staging")


def test_p33_same_endpoint_candidate_is_excluded_without_changing_way_result() -> None:
    way = evaluate_way("100", ["1", "1"], {"highway": "residential"})
    node = evaluate_node("1", {})
    candidate = _candidate_record("100", 0, ["1", "1"], way, {"1": node})
    assert way.eligibility == "include"
    assert candidate["eligibility"] == "exclude"
    assert candidate["reason_codes"] == ["A_DEFAULT", "H_DEFAULT_INCLUDE", "D_BOTH", "B_PASS", "G_ZERO_LENGTH"]
    assert candidate["geometry_check"] == "not_run"


def test_candidate_node_reason_evidence_is_stable_when_endpoint_order_is_reversed() -> None:
    way = evaluate_way("100", ["1", "2"], {"highway": "residential"})
    blocked = evaluate_node("1", {"barrier": "wall"})
    unknown = evaluate_node("2", {"barrier": "gate"})
    forward = _candidate_record("100", 0, ["1", "2"], way, {"1": blocked, "2": unknown})
    reverse = _candidate_record("100", 0, ["2", "1"], way, {"1": blocked, "2": unknown})
    assert forward["eligibility"] == reverse["eligibility"] == "exclude"
    assert forward["reason_codes"] == reverse["reason_codes"]
    assert forward["way_id"] == reverse["way_id"] == "100"
    assert set((forward["from_node_id"], forward["to_node_id"])) == set((reverse["from_node_id"], reverse["to_node_id"])) == {"1", "2"}
    assert forward["from_node_id"] == "1"
    assert reverse["from_node_id"] == "2"
