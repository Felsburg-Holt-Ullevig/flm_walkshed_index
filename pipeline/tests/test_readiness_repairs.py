from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import tracemalloc

import pytest

from flm_pipeline import cli, extractor, gpkg_export
from flm_pipeline.config import load_config

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "pipeline/config/denver-source.example.toml"


def write_records(directory: Path, records: dict[str, list[dict]]) -> None:
    for name in ("nodes", "ways", "relations"):
        with (directory / f"{name}.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for record in records.get(name, []):
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")


@pytest.mark.parametrize("field", ["node_id", "way_id", "relation_id", "way_ref", "relation_ref"])
@pytest.mark.parametrize("value", [1, True, 1.0, None])
def test_canonical_ids_reject_nontext_types(tmp_path: Path, field: str, value: object) -> None:
    records = {
        "nodes": [{"osm_id": "1", "lon": 1, "lat": 1, "tags": {}}],
        "ways": [{"osm_id": "10", "node_refs": ["1", "1"], "tags": {}}],
        "relations": [{"osm_id": "20", "members": [{"type": "way", "ref": "10", "role": "", "resolved": True}], "tags": {}}],
    }
    if field == "way_ref":
        records["ways"][0]["node_refs"][0] = value
    elif field == "relation_ref":
        records["relations"][0]["members"][0]["ref"] = value
    else:
        records[{"node_id": "nodes", "way_id": "ways", "relation_id": "relations"}[field]][0]["osm_id"] = value
    write_records(tmp_path, records)
    with pytest.raises(extractor.ExtractionFailure, match="positive decimal string"):
        extractor.validate_output_directory(tmp_path)
    assert not list(tmp_path.parent.glob("canonical-validation-*"))


def test_reader_conversion_and_no_location_cache(tmp_path: Path) -> None:
    assert extractor._reader_id(9007199254740993, "node", "test") == "9007199254740993"
    with pytest.raises(extractor.ExtractionFailure):
        extractor._id(9007199254740993, "node", "test")
    calls = []

    class Handler:
        def apply_file(self, path: str, *, locations: bool) -> None:
            calls.append((path, locations))

    with sqlite3.connect(":memory:") as connection:
        extractor._apply(connection, tmp_path / "source.pbf", Handler(), "test", {})
    assert calls == [(str(tmp_path / "source.pbf"), False)]


def test_canonical_validation_memory_does_not_scale_with_record_count(tmp_path: Path) -> None:
    peaks = []
    for count in (2000, 20000):
        with (tmp_path / "nodes.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for number in range(1, count + 1):
                stream.write(json.dumps({"osm_id": str(number), "lon": 1, "lat": 1, "tags": {"name": "x" * 100}}, sort_keys=True, separators=(",", ":")) + "\n")
        (tmp_path / "ways.jsonl").write_text("", encoding="utf-8")
        (tmp_path / "relations.jsonl").write_text("", encoding="utf-8")
        tracemalloc.start()
        try:
            result = extractor.validate_output_directory(tmp_path)
            peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            tracemalloc.stop()
        assert result["nodes.jsonl"]["count"] == count
    assert peaks[1] < 4 * 1024 * 1024
    assert peaks[1] < peaks[0] + 2 * 1024 * 1024


def test_canonical_record_limit_fails_without_leaving_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_records(tmp_path, {"nodes": [{"osm_id": "1", "lon": 1, "lat": 1, "tags": {"name": "x" * 1000}}]})
    monkeypatch.setattr(extractor, "MAX_CANONICAL_RECORD_BYTES", 128)
    with pytest.raises(extractor.ExtractionFailure, match="Canonical record exceeds"):
        extractor.validate_output_directory(tmp_path)
    assert not list(tmp_path.parent.glob("canonical-validation-*"))


@pytest.mark.parametrize("mode", ["timeout", "rss", "nonzero_exit", "child_cleanup", "array_result", "invalid_json", "array_report"])
def test_export_supervisor_failure_overrides_passing_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    def failed(command, cwd, log_path, timeout_seconds, rss_limit):
        result_path = Path(command[command.index("--result") + 1])
        payload = "{" if mode == "invalid_json" else json.dumps([] if mode == "array_result" else {"status": "pass"})
        result_path.write_text(payload, encoding="utf-8")
        if mode == "array_report":
            candidate = result_path.parent / "candidate"
            candidate.mkdir()
            (candidate / "run-report.json").write_text("[]", encoding="utf-8")
        assert timeout_seconds == load_config(EXAMPLE).limit_seconds
        assert rss_limit == load_config(EXAMPLE).limit_rss_bytes
        return {"exit_code": 7 if mode == "nonzero_exit" else 0, "failure_reason": {"timeout": "stage exceeded 1 seconds", "rss": "sampled process-tree RSS exceeded 1024 bytes"}.get(mode), "child_cleanup_complete": mode != "child_cleanup", "duration_seconds": 1, "sampled_peak_rss_bytes": 1024, "sample_interval_seconds": 1}

    monkeypatch.setattr(cli, "_supervise", failed)
    code, result = gpkg_export.export_extraction(EXAMPLE, tmp_path)
    assert code == 1 and result["status"] == "fail"
    assert not (load_config(EXAMPLE).output_root / result["export_run_id"]).exists()
    report = json.loads((ROOT / result["run_report"]).read_text(encoding="utf-8"))
    assert report["status"] == "fail" and report["worker"]


def test_export_worker_startup_is_subject_to_real_rss_limit(tmp_path: Path) -> None:
    config_path = tmp_path / "low-rss.toml"
    config_path.write_text(EXAMPLE.read_text(encoding="utf-8").replace("rss_bytes = 4294967296", "rss_bytes = 1024"), encoding="utf-8")
    code, result = gpkg_export.export_extraction(config_path, tmp_path)
    assert code == 1
    report = json.loads((ROOT / result["run_report"]).read_text(encoding="utf-8"))
    assert report["worker"]["failure_reason"] == "sampled process-tree RSS exceeded 1024 bytes"
    assert report["worker"]["child_cleanup_complete"] is True
    assert not (load_config(config_path).output_root / result["export_run_id"]).exists()


@pytest.mark.parametrize("broken", ["missing_way_node", "incorrect_relation_flag"])
def test_disk_index_checks_required_references_and_relation_flags(tmp_path: Path, broken: str) -> None:
    records = {
        "nodes": [{"osm_id": "9007199254740993", "lon": 1, "lat": 1, "tags": {}}],
        "ways": [{"osm_id": "10", "node_refs": ["9007199254740993", "9007199254740993"], "tags": {}}],
        "relations": [{"osm_id": "20", "members": [{"type": "relation", "ref": "21", "role": "child", "resolved": True}], "tags": {}}, {"osm_id": "21", "members": [{"type": "node", "ref": "999", "role": "outside", "resolved": False}], "tags": {}}],
    }
    write_records(tmp_path, records)
    assert extractor.validate_output_directory(tmp_path)["relations.jsonl"]["count"] == 2
    if broken == "missing_way_node":
        records["ways"][0]["node_refs"][1] = "2"
        message = "unresolved emitted node"
    else:
        records["relations"][0]["members"][0]["resolved"] = False
        message = "incorrect resolved flag"
    write_records(tmp_path, records)
    with pytest.raises(extractor.ExtractionFailure, match=message):
        extractor.validate_output_directory(tmp_path)


@pytest.mark.parametrize("failure", ["promotion", "final_report"])
def test_export_failed_completion_retains_candidate_without_published_report(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    from test_extractor import _write_pbf, _prepare_inputs, _invoke_extract

    pbf = tmp_path / "completion-failure.osm.pbf"
    _write_pbf(pbf, nodes=[(1, (0.5, 0.5), {}), (2, (1.5, 1.5), {})], ways=[(10, [1, 2], {"highway": "path"})])
    config, inventory, inventory_report = _prepare_inputs(tmp_path, pbf)
    code, extraction = _invoke_extract(config, inventory, inventory_report, capsys)
    assert code == 0
    original_promote = gpkg_export._promote
    original_write = gpkg_export._write_report

    def promote(source, destination):
        if failure == "promotion" and source.name == "candidate":
            raise OSError("simulated promotion failure")
        original_promote(source, destination)

    def write(path, report):
        if failure == "final_report" and path.parent.parent == load_config(config).output_root:
            raise OSError("simulated final report failure")
        original_write(path, report)

    monkeypatch.setattr(gpkg_export, "_promote", promote)
    monkeypatch.setattr(gpkg_export, "_write_report", write)
    code, result = gpkg_export.export_extraction(config, ROOT / extraction["output_directory"])
    assert code == 1 and result["status"] == "fail"
    assert not (load_config(config).output_root / result["export_run_id"]).exists()
    failed_report = ROOT / result["run_report"]
    assert json.loads(failed_report.read_text(encoding="utf-8"))["status"] == "fail"
    assert (failed_report.parent / "candidate/source-network.gpkg").is_file()
