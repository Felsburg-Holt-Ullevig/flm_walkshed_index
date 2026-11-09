"""Read-only, independently versioned comparison of frozen experimental graphs."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import UTC, datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

from flm_pipeline.classification import _hash_file, _json_bytes, _jsonl, _load_object, _validate_inputs, _write_json
from flm_pipeline.code_identity import code_identity
from flm_pipeline.graph import GEOD, GRAPH_VERSION, validate_graph
from flm_pipeline.pedestrian_config import load_pedestrian_settings
from flm_pipeline.runtime import runtime_versions

ROOT = Path(__file__).resolve().parents[2]
VERSION = "graph-policy-review-1"
REFERENCE = "reference-classification-6068f1b"
REVISION = "6068f1b8719d025426443230bb4a39a296b4f583"
REFERENCE_BLOBS = {"road-network.md": "f74dd6e25d2a73c651dfa627b796d4c2dee9ff7c", "road-network.js": "170f89a5b22202c50f8c62d4ae94d703cc1c296a", "walk-audit.js": "976012cc3242f5303e9a436a868d3f20bcc49448"}


def require(value, message):
    if not value:
        raise ValueError(message)


def numeric(value):
    return len(value), value


def reference_eligibility(tags):
    foot = tags.get("foot")
    if foot in {"yes", "designated", "permissive"}:
        return "include"
    if foot == "no":
        return "exclude"
    return "exclude" if tags.get("highway") in {"motorway", "motorway_link", "trunk", "trunk_link"} else "include"


def reference_sidewalk(tags):
    if tags.get("footway") == "sidewalk" or tags.get("highway") in {"footway", "path", "steps", "pedestrian", "cycleway"}:
        return "footway"
    sw = tags.get("sidewalk", "").lower()
    return "both" if sw in {"yes", "both"} else "one-side" if sw in {"left", "right"} else "none" if sw in {"no", "none", "separate"} else "unknown"


class Components:
    """Source-ID adjacency; parallel arcs retained in totals, not duplicated in DFS."""
    def __init__(self):
        self.xy = {}
        self.adj = defaultdict(set)
        self.rev = defaultdict(set)
        self.pairs = []

    def add(self, a, b, xy, length, direction, way_id):
        for node, coordinate in zip((a, b), xy, strict=True):
            require(node not in self.xy or self.xy[node] == coordinate, "Node coordinates disagree across source pairs")
            self.xy[node] = coordinate
        if direction in {"forward", "both"}:
            self.adj[a].add(b); self.rev[b].add(a)
        if direction in {"reverse", "both"}:
            self.adj[b].add(a); self.rev[a].add(b)
        self.pairs.append((a, b, length, way_id, direction))

    def finish(self, bbox):
        # Iterative DFS avoids recursion limits on long source chains.
        seen, order = set(), []
        for start in sorted(self.xy, key=numeric):
            if start in seen:
                continue
            seen.add(start)
            stack = [(start, iter(sorted(self.adj[start], key=numeric)))]
            while stack:
                node, children = stack[-1]
                child = next(children, None)
                if child is None:
                    order.append(node); stack.pop()
                elif child not in seen:
                    seen.add(child); stack.append((child, iter(sorted(self.adj[child], key=numeric))))
        strong, groups = {}, []
        for start in reversed(order):
            if start in strong:
                continue
            group, pending = [], [start]
            strong[start] = "pending"
            while pending:
                node = pending.pop(); group.append(node)
                for other in self.rev[node]:
                    if other not in strong:
                        strong[other] = "pending"; pending.append(other)
            identifier = "strong/" + min(group, key=numeric)
            for node in group:
                strong[node] = identifier
            groups.append(len(group))
        weak, summaries = {}, {}
        for start in sorted(self.xy, key=numeric):
            if start in weak:
                continue
            identifier = "component/" + start
            pending = [start]; weak[start] = identifier; nodes = []
            while pending:
                node = pending.pop(); nodes.append(node)
                for other in self.adj[node] | self.rev[node]:
                    if other not in weak:
                        weak[other] = identifier; pending.append(other)
            xs = [self.xy[node][0] for node in nodes]; ys = [self.xy[node][1] for node in nodes]
            summaries[identifier] = {"component_id": identifier, "node_count": len(nodes), "source_segments": 0, "directed_arcs": 0, "length_ft": 0.0,
                "bbox": [min(xs), min(ys), max(xs), max(ys)], "sample_node_ids": sorted(nodes, key=numeric)[:5], "sample_way_ids": [],
                "outside_extract_node_count": sum(not (bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]) for x, y in zip(xs, ys, strict=True))}
        for a, b, length, way, direction in self.pairs:
            row = summaries[weak[a]]
            require(weak[a] == weak[b], "Component endpoint reconciliation failed")
            row["source_segments"] += 1; row["length_ft"] += length
            row["directed_arcs"] += 2 if direction == "both" else 1
            if way not in row["sample_way_ids"] and len(row["sample_way_ids"]) < 5:
                row["sample_way_ids"].append(way)
        self.weak, self.strong = weak, strong
        self.rows = sorted(summaries.values(), key=lambda row: (-row["node_count"], numeric(row["component_id"].split("/")[1])))
        return {"nodes": len(self.xy), "source_segments": len(self.pairs), "directed_arcs": sum(row["directed_arcs"] for row in self.rows),
            "weak_components": len(self.rows), "strong_components": len(groups), "largest_weak_nodes": self.rows[0]["node_count"] if self.rows else 0,
            "largest_strong_nodes": max(groups, default=0), "components_with_two_nodes": sum(row["node_count"] == 2 for row in self.rows),
            "length_ft": math.fsum(pair[2] for pair in self.pairs)}


def _csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8"); return
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def _jsonlines(path, rows):
    with path.open("wb") as stream:
        for row in rows:
            stream.write(_json_bytes(row) + b"\n")


def _distance(xy):
    return GEOD.inv(-105.0006, 39.7530, *xy)[2] / .3048


def _gaps(graph, limit=100):
    """Screen degree-one endpoints within 100 feet; never alter connectivity."""
    from pyproj import Transformer
    from shapely import STRtree
    from shapely.geometry import Point
    ids = sorted((node for node in graph.xy if len(graph.adj[node] | graph.rev[node]) == 1), key=numeric)
    transform = Transformer.from_crs(4326, 26913, always_xy=True)
    points = []
    for node in ids:
        x, y = transform.transform(*graph.xy[node]); points.append(Point(x / .3048, y / .3048))
    if not points:
        return {"endpoint_count": 0, "candidate_pairs": 0, "nearest_pairs": []}
    tree = STRtree(points); results = []
    for i, point in enumerate(points):
        for j in tree.query(point, predicate="dwithin", distance=101):
            if j <= i or graph.weak[ids[i]] == graph.weak[ids[j]]:
                continue
            a, b = ids[i], ids[j]
            feet = GEOD.inv(*graph.xy[a], *graph.xy[b])[2] / .3048
            if feet <= 100:
                results.append({"from_node_id": a, "to_node_id": b, "distance_ft": feet, "from_component": graph.weak[a], "to_component": graph.weak[b], "coordinates": [graph.xy[a], graph.xy[b]]})
    results.sort(key=lambda row: (row["distance_ft"], numeric(row["from_node_id"]), numeric(row["to_node_id"])))
    return {"endpoint_count": len(ids), "candidate_pairs": len(results), "nearest_pairs": results[:limit],
        "method": "EPSG:26913 international-foot screening at 101 ft; exact WGS84 geodesic filter <=100 ft. Degree-one endpoints in different weak components only; candidate geometry is not proof of a missing connection."}


def review(graph_dir, reference_dir, output, review_cases=None, progress=print):
    graph_dir, reference_dir, output = Path(graph_dir).resolve(), Path(reference_dir).resolve(), Path(output)
    output = output.resolve()
    require(output.is_relative_to(ROOT) and not output.is_relative_to(ROOT / "data/raw") and not output.is_relative_to(graph_dir), "Review output must stay in repository outside raw inputs and the graph input")
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    identity = code_identity()
    report_path = graph_dir / "run-report.json"
    report = _load_object(report_path, "graph report")
    require(report.get("report_version") == GRAPH_VERSION and report.get("checks") and all(v is True for v in report["checks"].values()), "Graph report is incomplete or unsupported")
    require(report["implementation_identity"] == identity, "Upstream pipeline differs from frozen graph; review requires the recorded implementation")
    tool_hash = _hash_file(Path(__file__))
    test_path = Path(__file__).parent / "tests/test_graph_review.py"
    frozen = {report_path: _hash_file(report_path), Path(__file__): tool_hash, test_path: _hash_file(test_path)}
    for name, item in report["output_files"].items():
        require(Path(name).name == name, "Unsafe graph manifest path")
        path = graph_dir / name
        require(path.stat().st_size == item["bytes"] and _hash_file(path) == item["sha256"], "Graph payload hash/size mismatch: " + name)
        frozen[path] = item["sha256"]
    extraction = Path(report["inputs"]["extraction_directory"])
    metadata, _, source_hashes = _validate_inputs(extraction)
    require(source_hashes == report["inputs"]["extraction_hashes"], "Source identity mismatch")
    frozen.update({extraction / name: digest for name, digest in source_hashes.items()})
    classification = Path(report["inputs"]["classification_directory"])
    for name, digest in report["inputs"]["classification_hashes"].items():
        require(_hash_file(classification / name) == digest, "Classification identity mismatch")
        frozen[classification / name] = digest
    settings = load_pedestrian_settings(ROOT / "pipeline/config/pedestrian-policy.example.toml")
    authority = ROOT / settings.rule_authority
    require(settings.config_sha256 == report["policy"]["config_sha256"] and _hash_file(authority) == report["policy"]["authority_sha256"], "Policy identity mismatch")
    frozen[settings.config_path] = settings.config_sha256; frozen[authority] = _hash_file(authority)
    reference_files = {}
    for name, expected_blob in REFERENCE_BLOBS.items():
        path = reference_dir / name; payload = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
        require(blob == expected_blob, "Reference source blob mismatch: " + name)
        reference_files[name] = {"git_blob": blob, "sha256": _hash_file(path)}; frozen[path] = _hash_file(path)
    if review_cases:
        frozen[Path(review_cases).resolve()] = _hash_file(Path(review_cases))
    progress("Verified frozen graph/source/reference hashes; reopening graph structure", flush=True)
    structural = validate_graph(graph_dir, settings.speed_mph)
    require(all(structural[key] == report["counts"][key] for key in structural), "Reopened graph counts disagree")
    connection = sqlite3.connect(output / "source-index.sqlite")
    connection.execute("CREATE TABLE nodes(id TEXT PRIMARY KEY, lon REAL, lat REAL, tags TEXT)")
    connection.execute("CREATE TABLE ways(id TEXT PRIMARY KEY, refs TEXT, tags TEXT)")
    try:
        for _, node in _jsonl(extraction / "nodes.jsonl", "source node"):
            connection.execute("INSERT INTO nodes VALUES (?,?,?,?)", (node["osm_id"], node["lon"], node["lat"], json.dumps(node["tags"])))
        for _, way in _jsonl(extraction / "ways.jsonl", "source way"):
            connection.execute("INSERT INTO ways VALUES (?,?,?)", (way["osm_id"], json.dumps(way["node_refs"]), json.dumps(way["tags"])))
        connection.commit()
        accepted, reference = Components(), Components()
        transition_counts, transition_lengths, reasons, reason_lengths = Counter(), defaultdict(list), Counter(), defaultdict(list)
        sidewalk, flags, differences, named = Counter(), Counter(), {}, {}
        requested = {}
        if review_cases:
            with Path(review_cases).open(encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    for token in row["source_ids"].split(";"):
                        if token.startswith("way/"):
                            requested[token[4:]] = row["case_id"] + " " + row["place"]
        previous_way = None
        with (output / "comparison.jsonl").open("wb") as comparisons, (output / "reference-arcs.jsonl").open("wb") as arc_stream:
            for number, (_, seg) in enumerate(_jsonl(graph_dir / "segments.jsonl", "graph candidate"), 1):
                if seg["way_id"] != previous_way:
                    previous_way = seg["way_id"]
                    source = connection.execute("SELECT refs,tags FROM ways WHERE id=?", (previous_way,)).fetchone()
                    require(source is not None, "Graph way missing from source")
                    refs, tags = json.loads(source[0]), json.loads(source[1])
                a, b = seg["from_node_id"], seg["to_node_id"]
                require(refs[seg["sequence"]:seg["sequence"] + 2] == [a, b], "Graph/source reference sequence differs")
                old = reference_eligibility(tags)
                zero = seg["length_ft"] == 0 or a == b
                if zero:
                    old = "exclude"
                transition = (seg["eligibility"], old)
                transition_counts[transition] += 1; transition_lengths[transition].append(seg["length_ft"])
                for reason in seg["reason_codes"]:
                    if seg["eligibility"] != "include":
                        reasons[(seg["eligibility"], reason)] += 1
                        reason_lengths[(seg["eligibility"], reason)].append(seg["length_ft"])
                sidewalk[(reference_sidewalk(tags), tags.get("highway", ""), tags.get("footway", ""), tags.get("sidewalk", ""))] += 1
                if seg["eligibility"] == "include":
                    accepted.add(a, b, seg["coordinates"], seg["length_ft"], seg["direction"], seg["way_id"])
                if old == "include":
                    reference.add(a, b, seg["coordinates"], seg["length_ft"], "both", seg["way_id"])
                    for reverse in (False, True):
                        direction = "reverse" if reverse else "forward"
                        arc_stream.write(_json_bytes({"edge_id": seg["candidate_id"] + "/" + direction, "candidate_id": seg["candidate_id"], "way_id": seg["way_id"], "sequence": seg["sequence"], "direction": direction,
                            "from_node_id": b if reverse else a, "to_node_id": a if reverse else b, "coordinates": list(reversed(seg["coordinates"])) if reverse else seg["coordinates"],
                            "length_ft": seg["length_ft"], "base_seconds": seg["length_ft"] * 3600 / (settings.speed_mph * 5280)}) + b"\n")
                comparisons.write(_json_bytes({"candidate_id": seg["candidate_id"], "accepted_eligibility": seg["eligibility"], "reference_eligibility": old, "accepted_direction": seg["direction"], "reference_direction": "both" if old == "include" else "none", "length_ft": seg["length_ft"]}) + b"\n")
                changed = seg["eligibility"] != old or (old == "include" and seg["direction"] != "both")
                if changed:
                    # Nearest source example per causal reason, without using proximity as a route connection.
                    distance = _distance(seg["coordinates"][0])
                    for reason in seg["reason_codes"]:
                        if reason in {"A_FOOT_DENY", "A_ACCESS_DENY", "A_FOOT_UNSUPPORTED", "A_ACCESS_UNSUPPORTED", "A_CONDITIONAL_UNRESOLVED", "A_VARIANT_UNSUPPORTED", "A_ACCESS_ALLOW", "B_ACCESS_BLOCK", "B_PHYSICAL_BLOCK", "B_UNRESOLVED", "B_LOCKED", "B_LOCK_UNRESOLVED", "S_UNSUPPORTED_STRUCTURE", "H_UNSUPPORTED", "H_LIFECYCLE", "H_FOOT_UNCONFIRMED", "H_LIMITED_ACCESS", "D_UNSUPPORTED", "D_FORWARD", "D_REVERSE"}:
                            if reason not in differences or (distance, number) < differences[reason][0]:
                                differences[reason] = ((distance, number), seg, tags.copy())
                if seg["way_id"] in requested and seg["way_id"] not in named:
                    named[seg["way_id"]] = (requested[seg["way_id"]], seg, tags.copy())
                flags["direction_changed"] += old == "include" and seg["eligibility"] == "include" and seg["direction"] != "both"
                if number % 100000 == 0:
                    progress(f"Compared {number:,} source segments", flush=True)
        bbox = metadata["coverage"]["extract_bbox"]
        progress("Computing weak and strong components for both scenarios", flush=True)
        summaries = {"accepted": accepted.finish(bbox), "reference": reference.finish(bbox)}
        for label, graph in (("accepted", accepted), ("reference", reference)):
            _csv(output / (label + "-components.csv"), graph.rows)
            _jsonlines(output / (label + "-membership.jsonl"), ({"node_id": node, "weak_component": graph.weak[node], "strong_component": graph.strong[node]} for node in sorted(graph.xy, key=numeric)))
        _jsonlines(output / "reference-nodes.jsonl", ({"node_id": node, "lon": reference.xy[node][0], "lat": reference.xy[node][1]} for node in sorted(reference.xy, key=numeric)))
        progress("Screening disconnected endpoints and assembling source cases", flush=True)
        gaps = _gaps(accepted)
        gap_lookup = {frozenset((row["from_node_id"], row["to_node_id"])): row for row in gaps["nearest_pairs"]}
        for row in gaps["nearest_pairs"]:
            row["direct_source_candidates"] = []
            row["endpoint_tags"] = {node: json.loads(connection.execute("SELECT tags FROM nodes WHERE id=?", (node,)).fetchone()[0]) for node in (row["from_node_id"], row["to_node_id"])}
        for _, seg in _jsonl(graph_dir / "segments.jsonl", "gap source evidence"):
            gap = gap_lookup.get(frozenset((seg["from_node_id"], seg["to_node_id"])))
            if gap:
                gap["direct_source_candidates"].append({"candidate_id": seg["candidate_id"], "eligibility": seg["eligibility"], "reason_codes": seg["reason_codes"]})
        _write_json(output / "gap-candidates.json", gaps)
        cases = []
        def case(label, seg, tags):
            endpoints = {node: json.loads(connection.execute("SELECT tags FROM nodes WHERE id=?", (node,)).fetchone()[0]) for node in (seg["from_node_id"], seg["to_node_id"])}
            return {"case": label, "candidate_id": seg["candidate_id"], "name": tags.get("name", "(unnamed source way)"), "way_id": seg["way_id"], "way_tags": tags,
                "from_node_id": seg["from_node_id"], "to_node_id": seg["to_node_id"], "endpoint_tags": endpoints, "coordinates": seg["coordinates"],
                "accepted_eligibility": seg["eligibility"], "accepted_direction": seg["direction"], "reason_codes": seg["reason_codes"], "reference_eligibility": reference_eligibility(tags),
                "length_ft": seg["length_ft"], "accepted_endpoint_components": [accepted.weak.get(node) for node in endpoints]}
        cases.extend(case("difference/" + reason, seg, tags) for reason, (_, seg, tags) in sorted(differences.items()))
        cases.extend(case(label, seg, tags) for _, (label, seg, tags) in sorted(named.items(), key=lambda item: numeric(item[0])))
        for label, graph in (("accepted", accepted), ("reference", reference)):
            for component in graph.rows[:3] + list(reversed(graph.rows[-5:])):
                for way in component["sample_way_ids"][:2]:
                    tags = json.loads(connection.execute("SELECT tags FROM ways WHERE id=?", (way,)).fetchone()[0])
                    cases.append({"case": label + "/component/" + component["component_id"], "component": component, "way_id": way, "name": tags.get("name", "(unnamed source way)"), "way_tags": tags})
        _write_json(output / "source-cases.json", cases)
        relation_counts, relation_examples = Counter(), []
        included_ways = {pair[3] for pair in accepted.pairs}
        for _, relation in _jsonl(graph_dir / "relations-audit.jsonl", "relation audit"):
            tags = relation["tags"]
            category = "explicit_foot_restriction" if "restriction:foot" in tags or "restriction:foot:conditional" in tags else "generic_restriction_no_foot_exemption" if relation["unsupported"] else "foot_exempt_restriction" if tags.get("type") == "restriction" else "other_relation"
            relation_counts[category] += 1
            touches = any(member["type"] == "way" and member["ref"] in included_ways for member in relation["members"])
            if relation["unsupported"]:
                relation_counts["unsupported_touching_included_way"] += touches
                relation_counts["unsupported_with_unresolved_members"] += relation["unresolved_members"] > 0
            if sum(row["category"] == category for row in relation_examples) < 3:
                relation_examples.append({"category": category, "touches_included_way": touches, **relation})
        _write_json(output / "relation-review.json", {"counts": dict(relation_counts), "examples": relation_examples, "interpretation": "The accepted conservative rule flags unmodeled restrictions. Generic vehicle-shaped turn tags do not establish pedestrian prohibition; policy is unchanged."})
        transition_rows = [{"accepted": a, "reference": b, "source_segments": amount, "length_ft": math.fsum(transition_lengths[a, b]), "length_miles": math.fsum(transition_lengths[a, b]) / 5280} for (a, b), amount in sorted(transition_counts.items())]
        reason_rows = [{"eligibility": status, "reason_code": reason, "candidate_count": amount, "length_ft": math.fsum(reason_lengths[status, reason])} for (status, reason), amount in sorted(reasons.items())]
        _csv(output / "eligibility-transitions.csv", transition_rows); _csv(output / "nonexclusive-reasons.csv", reason_rows)
        _csv(output / "sidewalk-comparison.csv", [{"reference_sidewalk": a, "highway": b, "footway": c, "sidewalk": d, "candidate_count": count} for (a, b, c, d), count in sorted(sidewalk.items())])
        require(sum(transition_counts.values()) == report["counts"]["candidates"], "Comparison candidates do not reconcile")
        require(summaries["accepted"]["nodes"] == report["counts"]["nodes"] and summaries["accepted"]["directed_arcs"] == report["counts"]["directed_arcs"], "Accepted component graph differs from validated input")
    finally:
        connection.close()
    (output / "source-index.sqlite").unlink()
    for path, digest in frozen.items():
        require(_hash_file(path) == digest, "Input changed during review: " + str(path))
    require(code_identity() == identity, "Upstream implementation changed during review")
    return {"report_version": VERSION, "status": "review_complete_gate_3_pending", "graph_report_sha256": frozen[report_path], "graph_directory": str(graph_dir),
        "upstream_implementation_identity": identity, "review_tool_sha256": tool_hash, "review_tests_sha256": frozen[test_path], "runtime": runtime_versions(),
        "source_sha256": report["inputs"]["source"]["sha256"], "reference_revision": REVISION, "reference_files": reference_files,
        "scenarios": {"accepted": {"scenario_id": settings.scenario_id, "rule_version": settings.rule_version, "graph_format": GRAPH_VERSION, "graph_status": report["status"], **summaries["accepted"]},
                      "reference": {"scenario_id": REFERENCE, "status": "comparison_only_not_approved_for_analysis", "direction": "both", **summaries["reference"]}},
        "transitions": transition_rows, "reason_counts_nonexclusive": reason_rows, "direction_changes": flags["direction_changed"], "relation_counts": dict(relation_counts),
        "gap_pair_count": gaps["candidate_pairs"], "source_case_count": len(cases), "coverage": metadata["coverage"],
        "checks": {"all_input_hashes_before_after": True, "pinned_reference_blobs_verified": True, "graph_structure_reopened": True, "source_pairs_reconciled": True, "component_counts_reconciled": True},
        "output_files": {path.name: {"bytes": path.stat().st_size, "sha256": _hash_file(path)} for path in sorted(output.iterdir()) if path.is_file()},
        "duration_seconds": round(time.monotonic() - start, 3), "analytical_promotion": "blocked_by_unknown_candidates_and_unsupported_restrictions",
        "limitations": ["Reference classification uses identical source IDs, selected candidates and WGS84 lengths; it does not reproduce old Overpass coverage, rounded-XY topology, turf lengths, connectors, exclusions, polygons or walksheds.",
            "Weak components ignore direction; strong components require directed mutual reachability. Neither proves geographic coverage or legal access.",
            "Endpoint proximity is only a candidate screen; no source omission, connection, or repair is inferred.",
            "All reference arcs are comparison artifacts. Zero-length candidates are excluded consistently for comparison, not a reproduction of legacy zero-length behavior.",
            "Gate 3 requires developer acceptance. No policy changes, source repairs, new authoritative benchmark, or regional traversal occurred."]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", type=Path, required=True); parser.add_argument("--reference-dir", type=Path, required=True)
    parser.add_argument("--review-cases", type=Path); parser.add_argument("--worker", action="store_true")
    parser.add_argument("--output", type=Path); parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if args.worker:
        _write_json(args.result, review(args.graph, args.reference_dir, args.output, args.review_cases)); return 0
    from flm_pipeline.cli import _supervise, _promote_directory
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    stage = ROOT / "data/staging/prototype" / ("graph-review-" + run_id); stage.mkdir()
    result = stage / "worker-result.json"; candidate = stage / "candidate"
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--graph", str(args.graph.resolve()), "--reference-dir", str(args.reference_dir.resolve()), "--output", str(candidate), "--result", str(result)]
    if args.review_cases:
        command.extend(["--review-cases", str(args.review_cases.resolve())])
    supervision = _supervise(command, ROOT, stage / "worker.log", 1200, 4 * 1024**3)
    if supervision["exit_code"] or supervision["failure_reason"] or not supervision["child_cleanup_complete"] or not result.exists():
        _write_json(stage / "run-report.json", {"status": "fail", "supervision": supervision}); print(str(stage)); return 1
    report = _load_object(result, "review result")
    final = ROOT / "data/generated/prototype/graph-review" / run_id; final.parent.mkdir(parents=True, exist_ok=True)
    require(not final.exists(), "Refusing to replace review")
    _promote_directory(candidate, final)
    for name, info in report["output_files"].items():
        require(_hash_file(final / name) == info["sha256"], "Promoted review payload mismatch")
    report.update(run_id=run_id, supervision=supervision)
    _write_json(final / "run-report.json.tmp", report); os.replace(final / "run-report.json.tmp", final / "run-report.json")
    print(json.dumps({"status": report["status"], "directory": final.relative_to(ROOT).as_posix(), "scenarios": report["scenarios"], "transitions": report["transitions"], "relations": report["relation_counts"], "gap_pairs": report["gap_pair_count"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
