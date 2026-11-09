"""Read-only frozen graph boundary for experimental traversal."""
import hashlib
import json
from pathlib import Path

from .graph import validate_graph
from .routing import Readiness, Segment


def load_graph(directory):
    """Recheck frozen output hashes and structure without demanding regeneration."""
    directory = Path(directory)
    report = json.loads((directory / "run-report.json").read_text(encoding="utf-8"))
    if report.get("report_version") != "experimental-routing-graph-1" or not all(report.get("checks", {}).get(key) is True for key in ("structural_validation", "counts_reconciled", "gpkg_all_records_reopened")):
        raise ValueError("Missing or invalid completed graph report")
    if not {"nodes.jsonl", "segments.jsonl", "arcs.jsonl", "relations-audit.jsonl", "routing.gpkg"} <= report["output_files"].keys():
        raise ValueError("Incomplete graph file manifest")
    for name, item in report["output_files"].items():
        if Path(name).name != name:
            raise ValueError("Unsafe graph file path")
        path = directory / name
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if path.stat().st_size != item["bytes"] or digest.hexdigest() != item["sha256"]:
            raise ValueError("Frozen graph output hash mismatch: " + name)
    counts = validate_graph(directory, report["policy"]["speed_mph"])
    def rows(name):
        with (directory / name).open(encoding="utf-8") as stream:
            for line in stream:
                yield json.loads(line)
    segments = [Segment(r["candidate_id"], r["from_node_id"], r["to_node_id"], r["length_ft"], r["direction"])
                for r in rows("segments.jsonl") if r["eligibility"] == "include"]
    coordinates = {r["node_id"]: (r["lon"], r["lat"]) for r in rows("nodes.jsonl")}
    blockers = []
    if counts["candidates_by_eligibility"].get("unknown", 0):
        blockers.append("unknown_candidates")
    relations = list(rows("relations-audit.jsonl"))
    if any(r["unsupported"] for r in relations):
        blockers.append("unsupported_restrictions")
    if any(r["unresolved_members"] for r in relations):
        blockers.append("unresolved_relation_members")
    # A bbox cannot prove continuation completeness. Every source node on or
    # outside the selected extract rectangle is a conservative frontier warning.
    coverage = report.get("coverage") or {}
    bbox = coverage.get("extract_bbox")
    frontier = ()
    if bbox is not None:
        west, south, east, north = bbox
        frontier = tuple(sorted(n for n, (x, y) in coordinates.items() if x <= west or x >= east or y <= south or y >= north))
    return segments, coordinates, Readiness(tuple(blockers), "not_established", frontier), report


def compare_core(original, expanded, *, cost_tolerance_seconds=1e-9, interval_tolerance_ft=1e-8):
    """Compare caller-clipped common-core observations for the same origin.

    Each observation carries source_sha256, policy_sha256, origin, core_bbox,
    candidates (ID -> disposition), node_seconds and intervals_ft. Source offsets
    remain in the full source segment's orientation after clipping. The runner
    must independently establish core membership before calling this function.
    """
    from .routing import number
    number(cost_tolerance_seconds)
    number(interval_tolerance_ft)
    for key in ("source_sha256", "policy_sha256", "origin", "core_bbox"):
        if not original.get(key) or original[key] != expanded.get(key):
            raise ValueError("Coverage comparison identity mismatch: " + key)
    differences = []
    for category, tolerance in (("candidates", None), ("node_seconds", cost_tolerance_seconds), ("intervals_ft", interval_tolerance_ft)):
        left, right = original[category], expanded[category]
        for identity in sorted(left.keys() | right.keys()):
            if identity not in left or identity not in right:
                differences.append({"category": category, "id": identity, "kind": "membership", "original": left.get(identity), "expanded": right.get(identity)})
                continue
            a, b = left[identity], right[identity]
            if category == "candidates":
                equal = a == b
            elif category == "node_seconds":
                number(a)
                number(b)
                equal = abs(a - b) <= tolerance
            else:
                for intervals in (a, b):
                    last = -1
                    for lo, hi in intervals:
                        number(lo)
                        number(hi)
                        if not last < lo < hi:
                            raise ValueError("Core intervals must be positive, sorted, disjoint unions")
                        last = hi
                equal = len(a) == len(b) and all(abs(x - y) <= tolerance for ia, ib in zip(a, b) for x, y in zip(ia, ib))
            if not equal:
                differences.append({"category": category, "id": identity, "kind": "value", "original": a, "expanded": b})
    return {"status": "differences_require_review" if differences else "agreement_supporting_evidence_only",
            "coverage_readiness": "not_established", "differences": differences}
