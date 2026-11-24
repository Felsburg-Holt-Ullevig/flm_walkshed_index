from contextlib import closing
import importlib.util
from pathlib import Path
import sqlite3

import pytest


TOOL = Path(__file__).resolve().parents[1] / "compare_larimer_networks.py"
spec = importlib.util.spec_from_file_location("compare_larimer_networks", TOOL)
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def _network(path, edges, nodes):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("CREATE TABLE pedestrian_edges (segment_id, from_node_id, to_node_id, geom)")
        db.executemany("INSERT INTO pedestrian_edges VALUES (?, ?, ?, X'00')", edges)
        db.execute("CREATE TABLE pedestrian_nodes (node_id)")
        db.executemany("INSERT INTO pedestrian_nodes VALUES (?)", [(node,) for node in nodes])


@pytest.mark.parametrize(
    ("candidate_edges", "message"),
    [
        ([("new", "a", "missing")], "share no segment IDs"),
        ([("shared", "a", "b"), ("new", "a", "missing")], "New segment new has missing saved endpoint to_node_id='missing'"),
    ],
)
def test_invalid_comparison_stops_before_writing_outputs(tmp_path, monkeypatch, candidate_edges, message):
    baseline = tmp_path / "baseline.gpkg"
    candidate = tmp_path / "candidate.gpkg"
    _network(baseline, [("shared", "a", "b")], ["a", "b"])
    _network(candidate, candidate_edges, ["a", "b"])
    monkeypatch.setattr(comparison, "BASELINE_SHA256", comparison.digest(baseline))
    audit = tmp_path / "audit.jsonl"
    csv = tmp_path / "result.csv"
    report = tmp_path / "result.json"
    with pytest.raises(ValueError, match=message):
        comparison.compare(baseline, candidate, audit, audit, csv, report)
    assert not csv.exists() and not report.exists()
