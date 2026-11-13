"""Prepare bounded, local OSM pedestrian-network samples around review origins."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path

from pyproj import Geod

GEOD_FT = Geod(a=20_925_646.325459316, rf=298.257223563)
SAMPLE_MARGIN_FT = 6_000.0
REQUIRED_MARGIN_FT = 5_000.0


class WalkSampleError(RuntimeError):
    """An input or sample preparation invariant failed."""


def _finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WalkSampleError(f"{label} must be a finite number")
    return float(value)


def sample_bbox(origin_lonlat, margin_ft=SAMPLE_MARGIN_FT):
    """Bound four cardinal geodesic offsets and verify the nearest box edge."""
    lon, lat = (_finite(value, "origin coordinate") for value in origin_lonlat)
    margin = _finite(margin_ft, "margin_ft")
    if not (-180 <= lon <= 180 and -90 <= lat <= 90) or margin <= 0:
        raise WalkSampleError("Origin or margin is outside supported bounds")
    points = [GEOD_FT.fwd(lon, lat, azimuth, margin)[:2] for azimuth in (0, 90, 180, 270)]
    bbox = (min(point[0] for point in points), min(point[1] for point in points),
            max(point[0] for point in points), max(point[1] for point in points))
    if bbox[0] < -180 or bbox[2] > 180 or bbox[1] < -90 or bbox[3] > 90:
        raise WalkSampleError("Sample margin crosses a coordinate-domain boundary")
    # Check the closest point on each lon/lat rectangle edge, not only its corners.
    west, south, east, north = bbox
    edges = [((west, south), (east, south)), ((west, north), (east, north)),
             ((west, south), (west, north)), ((east, south), (east, north))]
    def edge_distance(a, b):
        lo, hi = 0.0, 1.0
        def distance(t):
            point = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            return GEOD_FT.inv(lon, lat, *point)[2]
        for _ in range(64):
            left = lo + (hi - lo) / 3
            right = hi - (hi - lo) / 3
            if distance(left) <= distance(right):
                hi = right
            else:
                lo = left
        return min(distance(0), distance(1), distance((lo + hi) / 2))
    minimum = min(edge_distance(*edge) for edge in edges)
    if minimum + 1e-7 < REQUIRED_MARGIN_FT:
        raise WalkSampleError(f"Bounding-box edge is only {minimum:.9f} ft from origin")
    return bbox, minimum


def _jsonl(path):
    with Path(path).open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise WalkSampleError(f"Invalid JSONL {path}:{number}: {error}") from error
            if not isinstance(row, dict):
                raise WalkSampleError(f"Expected JSON object at {path}:{number}")
            yield row


def build_sample_records(graph_directory, extraction_directory, bbox):
    """Select whole source ways touching the sample box and preserve included segments."""
    west, south, east, north = bbox
    ways = {}
    touched = set()
    for way in _jsonl(Path(extraction_directory) / "ways.jsonl"):
        way_id = way.get("osm_id")
        refs = way.get("node_refs")
        if not isinstance(way_id, str) or way_id in ways or not isinstance(refs, list) or not refs:
            raise WalkSampleError("Malformed or duplicate extracted way")
        ways[way_id] = way
    source_nodes = {node["osm_id"]: node for node in _jsonl(Path(extraction_directory) / "nodes.jsonl")}
    for way_id, way in ways.items():
        if any(node_id not in source_nodes for node_id in way["node_refs"]):
            raise WalkSampleError(f"Way {way_id} has a missing source node")
        if any(west <= source_nodes[node_id]["lon"] <= east and south <= source_nodes[node_id]["lat"] <= north
               for node_id in way["node_refs"]):
            touched.add(way_id)
    selected = {}
    dispositions = Counter()
    for segment in _jsonl(Path(graph_directory) / "segments.jsonl"):
        way_id = segment.get("way_id")
        if way_id not in touched:
            continue
        disposition = segment.get("eligibility")
        if disposition not in {"include", "exclude", "unknown"}:
            raise WalkSampleError("Graph segment has invalid eligibility")
        dispositions[disposition] += 1
        if disposition == "include":
            selected[segment["candidate_id"]] = segment
    sample_nodes = {}
    package_segments = []
    for key in sorted(selected, key=lambda item: (len(selected[item]["way_id"]), selected[item]["way_id"], selected[item]["sequence"])):
        segment = selected[key]
        way = ways.get(segment["way_id"])
        if way is None:
            raise WalkSampleError(f"Missing source way {segment['way_id']}")
        for node_id, coordinate in zip((segment["from_node_id"], segment["to_node_id"]), segment["coordinates"], strict=True):
            source_node = source_nodes.get(node_id)
            if source_node is None or [source_node["lon"], source_node["lat"]] != coordinate:
                raise WalkSampleError(f"Endpoint/source node mismatch for {segment['candidate_id']}")
            sample_nodes[node_id] = {"node_id": node_id, "coordinate": coordinate}
        package_segments.append({key: segment[key] for key in (
            "candidate_id", "way_id", "sequence", "from_node_id", "to_node_id", "direction", "length_ft", "coordinates")})
    arcs = [arc for arc in _jsonl(Path(graph_directory) / "arcs.jsonl") if arc.get("candidate_id") in selected]
    if len(arcs) != sum(2 if row["direction"] == "both" else 1 for row in package_segments):
        raise WalkSampleError("Selected segment and directed-arc counts disagree")
    return package_segments, list(sample_nodes.values()), arcs, {key: ways[key] for key in touched}, {
        "selected_ways": len(touched), "included_segments": len(package_segments),
        "excluded_segments": dispositions["exclude"], "unknown_segments": dispositions["unknown"],
        "nodes": len(sample_nodes), "directed_arcs": len(arcs),
    }
