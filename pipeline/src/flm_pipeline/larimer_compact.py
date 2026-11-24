"""Conservative compaction and pruning of the Larimer pedestrian export.

Node IDs remain the topology authority: lines that merely cross in their
coordinates are never joined.  The input GeoPackage is read-only.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Collection, Iterable

import geopandas as gpd
from pyogrio import read_dataframe, read_info
from shapely.geometry import LineString, Point, box, mapping
from shapely.ops import transform
from shapely.strtree import STRtree
from pyproj import Transformer

from .classification import _hash_file
from .larimer_export import CRS, _verify_layer, _write_layer

COMPACT_FILENAME = "larimer_pedestrian_network_compact.gpkg"
REMOVED_FILENAME = "removed-fragments.jsonl"
REPORT_FILENAME = "compact-build-report.json"
PRUNED_GEOJSON_FILENAME = "deleted-service-segments.geojson"
SIMPLIFICATION_FEET = 10.0
PRUNE_LENGTH_FEET = 200.0
BOUNDARY_MARGIN_FEET = 200.0
AUDIT_WAY_TAGS = (
    "foot", "access", "service", "surface", "smoothness", "width", "lit", "crossing",
    "footway", "oneway", "oneway:foot", "foot:conditional", "access:conditional",
    "motor_vehicle", "vehicle", "bicycle", "wheelchair", "incline", "steps", "step_count",
    "bridge", "tunnel", "layer", "designation", "tracktype", "trail_visibility", "maxspeed",
    "barrier", "kerb", "ramp", "segregated", "covered",
)
_TO_METERS = Transformer.from_crs(CRS, "EPSG:26913", always_xy=True).transform
_TO_WGS84 = Transformer.from_crs("EPSG:26913", CRS, always_xy=True).transform


@dataclass
class _Edge:
    row: dict[str, Any]
    geom: LineString
    original_geom: LineString

    @property
    def edge_id(self) -> str:
        return str(self.row["segment_id"])


def _norm_name(value: Any) -> str:
    return "" if value is None or (isinstance(value, float) and value != value) else str(value).strip()


def _direction_reversed(value: Any) -> Any:
    if value == "forward":
        return "reverse"
    if value == "reverse":
        return "forward"
    return value


def _edge_key(row: dict[str, Any]) -> tuple[Any, ...]:
    ignored = {"segment_id", "way_id", "from_node_id", "to_node_id", "length_ft", "geometry"}
    return tuple((key, row.get(key)) for key in sorted(row) if key not in ignored)


def _edge_rows(path: Path) -> tuple[list[_Edge], dict[str, Point]]:
    info = read_info(path, layer="pedestrian_edges", force_feature_count=True)
    if info["crs"] != CRS or info["geometry_type"] != "LineString":
        raise ValueError("pedestrian_edges must be EPSG:4326 LineStrings")
    frame = read_dataframe(path, layer="pedestrian_edges")
    nodes_frame = read_dataframe(path, layer="pedestrian_nodes")
    if nodes_frame.crs is None or str(nodes_frame.crs).upper() != CRS:
        raise ValueError("pedestrian_nodes must be EPSG:4326")
    nodes = {str(row.node_id): row.geometry for row in nodes_frame.itertuples(index=False)}
    edges: list[_Edge] = []
    for row in frame.itertuples(index=False):
        data = {key: (None if value is None or (isinstance(value, float) and value != value) else value) for key, value in row._asdict().items() if key != "geometry"}
        data["segment_id"] = str(data["segment_id"])
        data["from_node_id"] = str(data["from_node_id"])
        data["to_node_id"] = str(data["to_node_id"])
        geom = row.geometry
        if not isinstance(geom, LineString) or geom.is_empty or len(geom.coords) < 2:
            raise ValueError(f"Invalid line geometry for {data['segment_id']}")
        if data["from_node_id"] not in nodes or data["to_node_id"] not in nodes:
            raise ValueError(f"Missing endpoint for {data['segment_id']}")
        edges.append(_Edge(data, geom, geom))
    return edges, nodes


def _component_members(edges: list[_Edge], indices: Collection[int] | None = None) -> list[list[int]]:
    indices = range(len(edges)) if indices is None else indices
    adjacency: dict[str, list[int]] = {}
    for index in indices:
        edge = edges[index]
        adjacency.setdefault(edge.row["from_node_id"], []).append(index)
        adjacency.setdefault(edge.row["to_node_id"], []).append(index)
    seen: set[int] = set()
    components: list[list[int]] = []
    for start in indices:
        if start in seen:
            continue
        stack = [start]
        component: list[int] = []
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            component.append(current)
            edge = edges[current]
            stack.extend(adjacency[edge.row["from_node_id"]])
            stack.extend(adjacency[edge.row["to_node_id"]])
        components.append(component)
    return components


_SERVICE_ACTIONS = {
    "driveway": "pruned_driveway_tail",
    "drive-through": "pruned_drive_through",
    "parking_aisle": "pruned_parking_aisle",
}


def _endpoints(edge: _Edge) -> tuple[str, str]:
    return edge.row["from_node_id"], edge.row["to_node_id"]


def _rows(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            yield json.loads(line)


def _pedestrian_evidence(tags: dict[str, str]) -> bool:
    return (
        any(tags.get(key) in {"yes", "designated", "permissive"} for key in ("foot", "access"))
        or any(key.startswith(("foot:", "access:")) for key in tags)
        or any(key.startswith("sidewalk") and value not in {"no", "none"} for key, value in tags.items())
    )


def _walking_destination(tags: dict[str, str]) -> bool:
    return (
        bool(tags.get("entrance") and tags["entrance"] != "no")
        or bool(tags.get("public_transport") and tags["public_transport"] != "no")
        or tags.get("highway") in {"bus_stop", "crossing", "elevator"}
        or tags.get("railway") in {"tram_stop", "station", "halt", "subway_entrance"}
        or _pedestrian_evidence(tags)
    )


def _terminal_edges(edges: list[_Edge], component: list[int], anchors: set[str]) -> set[int]:
    """Peel dead ends while keeping all paths between attachment nodes."""
    if len(anchors) == 1:
        return set(component)
    incident: dict[str, set[int]] = defaultdict(set)
    for index in component:
        for node in _endpoints(edges[index]):
            incident[node].add(index)
    leaves = deque(node for node, links in incident.items() if node not in anchors and len(links) == 1)
    removed: set[int] = set()
    while leaves:
        node = leaves.popleft()
        if len(incident[node]) != 1:
            continue
        index = next(iter(incident[node]))
        start, end = _endpoints(edges[index])
        if start == end:
            continue
        removed.add(index)
        for endpoint in (start, end):
            incident[endpoint].remove(index)
            if endpoint not in anchors and len(incident[endpoint]) == 1:
                leaves.append(endpoint)
    return removed


def _vehicle_access_pruning(
    edges: list[_Edge], core: Any, extraction: Path, classification: Path,
) -> tuple[dict[int, str], set[str], set[str]]:
    ways = {way["osm_id"]: way for way in _rows(extraction / "ways.jsonl")}
    protected_ways = {way_id for way_id, way in ways.items() if _pedestrian_evidence(way["tags"])}
    protected_nodes = {
        node["osm_id"] for node in _rows(extraction / "nodes.jsonl") if _walking_destination(node["tags"])
    }
    classified_ways: set[str] = set()
    restricted_ways: set[str] = set()
    for record in _rows(classification / "ways-classified.jsonl"):
        evaluation = record["evaluation"]
        way_id = evaluation["osm_id"]
        classified_ways.add(way_id)
        access_denied = {"A_ACCESS_DENY", "A_FOOT_DENY"}.intersection(evaluation["reason_codes"])
        if evaluation["eligibility"] == "exclude" and access_denied:
            restricted_ways.add(way_id)
    if ways.keys() != classified_ways:
        raise ValueError("OSM extraction and classification cover different source ways")

    candidates: dict[int, str] = {}
    network_nodes: set[str] = set()
    for index, edge in enumerate(edges):
        way_id = str(edge.row["way_id"])
        tags = ways[way_id]["tags"]
        service = tags.get("service")
        if (
            tags.get("highway") == "service" and service in _SERVICE_ACTIONS
            and not _norm_name(edge.row.get("name")) and way_id not in protected_ways
        ):
            candidates[index] = service
        else:
            network_nodes.update(_endpoints(edge))

    removed: dict[int, str] = {}
    isolated: list[tuple[list[int], set[str], set[str]]] = []
    isolated_nodes: set[str] = set()
    for component in _component_members(edges, candidates):
        nodes = {node for index in component for node in _endpoints(edges[index])}
        if not all(core.contains(edges[index].geom) for index in component):
            continue
        attachments = nodes & network_nodes
        destinations = nodes & protected_nodes
        if attachments:
            for index in _terminal_edges(edges, component, attachments | destinations):
                removed[index] = _SERVICE_ACTIONS[candidates[index]]
        elif not destinations and all(candidates[index] == "driveway" for index in component):
            way_ids = {str(edges[index].row["way_id"]) for index in component}
            isolated.append((component, nodes, way_ids))
            isolated_nodes.update(nodes)

    touching_ways: dict[str, set[str]] = defaultdict(set)
    for way_id, way in ways.items():
        for node in way["node_refs"]:
            if node in isolated_nodes:
                touching_ways[node].add(way_id)
    for component, nodes, way_ids in isolated:
        outside = set().union(*(touching_ways[node] for node in nodes)) - way_ids
        if outside and outside <= restricted_ways:
            removed.update(dict.fromkeys(component, "pruned_driveway_restricted_only"))
    return removed, protected_nodes, protected_ways


def _component_is_prunable(edges: list[_Edge], indices: list[int], boundary: Any | None) -> bool:
    if sum(float(edges[i].row["length_ft"]) for i in indices) >= PRUNE_LENGTH_FEET:
        return False
    if any(_norm_name(edges[i].row.get("name")) or edges[i].row.get("highway") != "service" for i in indices):
        return False
    if boundary is None:
        return False
    geom = gpd.GeoSeries([edges[i].geom for i in indices], crs=CRS).to_crs("EPSG:26913").unary_union
    # Conservative: require the complete component inside a 200-foot inset.
    return bool(boundary.buffer(-BOUNDARY_MARGIN_FEET * 0.3048).contains(geom))


def _chain_geometry(chain: list[tuple[_Edge, bool]]) -> LineString:
    coordinates: list[tuple[float, float]] = []
    for edge, reverse in chain:
        points = list(edge.geom.coords)
        if reverse:
            points.reverse()
        if coordinates and coordinates[-1] != tuple(points[0]):
            raise ValueError("Chain endpoint geometry is discontinuous")
        coordinates.extend(tuple(xy) for xy in points if not coordinates or tuple(xy) != coordinates[-1])
    return LineString(coordinates)


def _simplify_without_crossings(raw: LineString, chain_ids: set[int], edges: list[_Edge], tree: STRtree, chain_index: int, raw_chains: list[LineString], chain_tree: STRtree, accepted: dict[int, LineString]) -> tuple[LineString, bool, bool]:
    projected = transform(_TO_METERS, raw)
    simplified_projected = projected.simplify(SIMPLIFICATION_FEET * 0.3048, preserve_topology=True)
    if len(simplified_projected.coords) == len(projected.coords) and simplified_projected.equals(projected):
        return raw, False, False
    simplified = transform(_TO_WGS84, simplified_projected)
    # Transform round-trips must not move source endpoints, which are the
    # topology anchors used by the two layers.
    simplified_coords = list(simplified.coords)
    simplified_coords[0] = tuple(raw.coords[0])
    simplified_coords[-1] = tuple(raw.coords[-1])
    simplified = LineString(simplified_coords)
    if simplified.is_empty or not isinstance(simplified, LineString) or len(simplified.coords) < 2:
        return raw, False, True
    for hit in tree.query(simplified):
        other_index = int(hit)
        if other_index in chain_ids:
            continue
        other = edges[other_index].original_geom
        # Roll back only intersections introduced by simplification. Existing
        # coordinate crossings (including grade-separated source crossings)
        # are evidence and must remain untouched.
        if simplified.intersects(other) and not raw.intersects(other):
            return raw, False, True
    for hit in chain_tree.query(simplified):
        other_index = int(hit)
        if other_index >= chain_index or other_index not in accepted:
            continue
        if simplified.intersects(accepted[other_index]) and not raw.intersects(raw_chains[other_index]):
            return raw, False, True
    return simplified, True, True


def _build_chains(edges: list[_Edge], removed: set[int]) -> list[list[tuple[int, bool]]]:
    adjacency: dict[str, list[int]] = {}
    for index, edge in enumerate(edges):
        if index in removed:
            continue
        adjacency.setdefault(edge.row["from_node_id"], []).append(index)
        adjacency.setdefault(edge.row["to_node_id"], []).append(index)

    def can_continue(node: str, incoming: _Edge) -> bool:
        candidates = [i for i in adjacency.get(node, []) if i not in removed and edges[i].edge_id != incoming.edge_id]
        return len(candidates) == 1 and _edge_key(edges[candidates[0]].row) == _edge_key(incoming.row)

    used: set[int] = set()
    chains: list[list[tuple[int, bool]]] = []
    for index, edge in enumerate(edges):
        if index in removed or index in used:
            continue
        endpoints = [edge.row["from_node_id"], edge.row["to_node_id"]]
        start = next((node for node in endpoints if not can_continue(node, edge)), None) or min(endpoints)
        chain: list[tuple[int, bool]] = []
        chain_direction: Any | None = None
        current_index, current_node = index, start
        while current_index not in used and current_index not in removed:
            current = edges[current_index]
            reverse = current.row["from_node_id"] != current_node
            # Don't produce a one-way output whose travel orientation changes
            # inside a chain; the original rows remain the safe representation.
            direction = current.row.get("direction")
            travelled = _direction_reversed(direction) if reverse else direction
            if direction in {"forward", "reverse"}:
                if chain_direction is not None and travelled != chain_direction:
                    break
                chain_direction = travelled
            chain.append((current_index, reverse))
            used.add(current_index)
            next_node = current.row["from_node_id"] if reverse else current.row["to_node_id"]
            # Degree is measured in the original active graph, not the set of
            # edges left after this walk.  This prevents a branch from looking
            # like a degree-2 continuation after one incident edge is used.
            if len(adjacency.get(next_node, [])) != 2:
                break
            candidates = [i for i in adjacency.get(next_node, []) if i not in used and i not in removed]
            if len(candidates) != 1 or _edge_key(edges[candidates[0]].row) != _edge_key(current.row):
                break
            current_index, current_node = candidates[0], next_node
        chains.append(chain)
    return chains


def _boundary_from_bbox(bounds: Iterable[float] | None) -> Any | None:
    if bounds is None:
        return None
    values = tuple(float(value) for value in bounds)
    if len(values) != 4 or not values[0] < values[2] or not values[1] < values[3]:
        raise ValueError("Boundary must be min_lon,min_lat,max_lon,max_lat")
    return transform(_TO_METERS, box(*values))


def compact_network(
    source: Path, destination: Path, *, boundary_bbox: Iterable[float] | None = None,
    osm_extraction: Path | None = None, osm_classification: Path | None = None,
    retain_osm_tags: bool = False,
) -> dict[str, Any]:
    """Compact *source* into *destination*, promoting only reopened output."""
    if destination.exists():
        raise FileExistsError(destination)
    if retain_osm_tags and osm_extraction is None:
        raise ValueError("Retaining original OSM tags requires the matching OSM extraction")
    if (osm_extraction is not None or osm_classification is not None) and (
        osm_extraction is None or osm_classification is None or boundary_bbox is None
    ):
        raise ValueError("Vehicle-access pruning requires the OSM extraction, classification, and boundary")
    source_hash = _hash_file(source)
    edges, nodes = _edge_rows(source)
    boundary = _boundary_from_bbox(boundary_bbox)
    actions: dict[int, str] = {}
    protected_nodes: set[str] = set()
    protected_ways: set[str] = set()
    if osm_extraction is not None and osm_classification is not None:
        core = transform(_TO_WGS84, boundary.buffer(-BOUNDARY_MARGIN_FEET * 0.3048))
        actions, protected_nodes, protected_ways = _vehicle_access_pruning(edges, core, osm_extraction, osm_classification)
    ledger: list[dict[str, Any]] = []
    pruned_components = 0
    for component in _component_members(edges):
        if not _component_is_prunable(edges, component, boundary):
            continue
        if any(
            str(edges[index].row["way_id"]) in protected_ways
            or protected_nodes.intersection(_endpoints(edges[index]))
            for index in component
        ):
            continue
        remaining = [index for index in component if index not in actions]
        if remaining:
            pruned_components += 1
            actions.update(dict.fromkeys(remaining, "pruned_service_component"))

    removed = set(actions)
    retained_tag_columns = {key.replace(":", "_"): key for key in AUDIT_WAY_TAGS} if retain_osm_tags else {}
    if retained_tag_columns and osm_extraction is not None:
        way_tags = {way["osm_id"]: way["tags"] for way in _rows(osm_extraction / "ways.jsonl")}
        for index, edge in enumerate(edges):
            if index not in removed:
                tags = way_tags[edge.row["way_id"]]
                edge.row.update({column: tags.get(key) for column, key in retained_tag_columns.items()})
    count_by_action = Counter(actions.values())
    length_by_action: dict[str, float] = defaultdict(float)
    for index, action in sorted(actions.items()):
        edge = edges[index]
        length = edge.row["length_ft"]
        length_by_action[action] += length
        ledger.append({
            "segment_id": edge.edge_id,
            "way_id": str(edge.row["way_id"]),
            "action": action,
            "geometry": mapping(edge.original_geom),
            "length_ft": length,
        })

    tree = STRtree([edge.original_geom for edge in edges])
    chains = _build_chains(edges, removed)
    prepared: list[tuple[list[tuple[int, bool]], LineString]] = []
    for chain in chains:
        chain_directions = {edges[index].row.get("direction") for index, _ in chain}
        if len(chain_directions) == 1 and chain_directions <= {"forward", "reverse"}:
            first_index, first_reverse = chain[0]
            first_direction = edges[first_index].row.get("direction")
            output_direction = _direction_reversed(first_direction) if first_reverse else first_direction
            if output_direction != first_direction:
                chain = [(index, not reverse) for index, reverse in reversed(chain)]
        prepared.append((chain, _chain_geometry([(edges[index], reverse) for index, reverse in chain])))
    chain_tree = STRtree([raw for _, raw in prepared])
    raw_chains = [raw for _, raw in prepared]
    output_edges: list[dict[str, Any]] = []
    simplified_count = 0
    reverted_count = 0
    merged_count = 0
    accepted: dict[int, LineString] = {}
    for chain_index, (chain, raw) in enumerate(prepared):
        chain_indices = {index for index, _ in chain}
        geom, simplified, attempted = _simplify_without_crossings(raw, chain_indices, edges, tree, chain_index, raw_chains, chain_tree, accepted)
        accepted[chain_index] = geom
        simplified_count += int(simplified and len(chain) > 1)
        reverted_count += int(attempted and not simplified and len(chain) > 1)
        first = edges[chain[0][0]]
        source_ids = [edges[index].edge_id for index, _ in chain]
        source_way_ids = list(dict.fromkeys(str(edges[index].row["way_id"]) for index, _ in chain))
        row = dict(first.row)
        row["segment_id"] = source_ids[0] if len(chain) == 1 else "compact/" + source_ids[0]
        row["from_node_id"] = first.row["to_node_id"] if chain[0][1] else first.row["from_node_id"]
        row["to_node_id"] = edges[chain[-1][0]].row["from_node_id"] if chain[-1][1] else edges[chain[-1][0]].row["to_node_id"]
        if chain[0][1]:
            row["direction"] = _direction_reversed(row.get("direction"))
        row["length_ft"] = sum(float(edges[index].row["length_ft"]) for index, _ in chain)
        row["source_segment_ids"] = json.dumps(source_ids, separators=(",", ":"))
        row["source_way_ids"] = json.dumps(source_way_ids, separators=(",", ":"))
        row["geometry"] = geom
        output_edges.append(row)
        if len(chain) > 1:
            merged_count += len(chain)
            for index, _ in chain:
                edge = edges[index]
                ledger.append({"segment_id": edge.edge_id, "action": "merged", "output_segment_id": row["segment_id"], "geometry": mapping(edge.original_geom), "length_ft": edge.row["length_ft"]})

    output_node_ids = {row["from_node_id"] for row in output_edges} | {row["to_node_id"] for row in output_edges}
    output_nodes = [{"node_id": node_id, "geometry": nodes[node_id]} for node_id in sorted(output_node_ids)]
    nullable_columns = {"name", "sidewalk", "sidewalk_left", "sidewalk_right", "sidewalk_both"} | retained_tag_columns.keys()
    output_edges = [{key: value for key, value in row.items() if value is not None or key in nullable_columns} for row in output_edges]
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / ("." + destination.name + ".staging")
    if staging.exists():
        raise FileExistsError(staging)
    staging.mkdir()
    try:
        gpkg = staging / COMPACT_FILENAME
        _write_layer(gpkg, "pedestrian_edges", iter(output_edges))
        _write_layer(gpkg, "pedestrian_nodes", iter(output_nodes))
        _verify_layer(gpkg, "pedestrian_edges", output_edges, "LineString", len(output_edges))
        _verify_layer(gpkg, "pedestrian_nodes", output_nodes, "Point", len(output_nodes))
        with (staging / REMOVED_FILENAME).open("w", encoding="utf-8") as stream:
            for item in sorted(ledger, key=lambda value: value["segment_id"]):
                stream.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
        deleted_features = [
            {"type": "Feature", "geometry": item["geometry"], "properties": {key: value for key, value in item.items() if key != "geometry"}}
            for item in ledger[:len(removed)]
        ]
        with (staging / PRUNED_GEOJSON_FILENAME).open("w", encoding="utf-8") as stream:
            json.dump({"type": "FeatureCollection", "features": deleted_features}, stream, separators=(",", ":"))
            stream.write("\n")
        if _hash_file(source) != source_hash:
            raise ValueError("Input GeoPackage changed during compaction")
        report = {
            "status": "pass",
            "source": {"path": str(source.resolve()), "sha256": source_hash, "bytes": source.stat().st_size},
            "output": {"path": str((destination / COMPACT_FILENAME).resolve()), "bytes": gpkg.stat().st_size, "sha256": _hash_file(gpkg), "layer_counts": {"pedestrian_edges": len(output_edges), "pedestrian_nodes": len(output_nodes)}},
            "simplification": {"tolerance_ft": SIMPLIFICATION_FEET, "merged_source_edges": merged_count, "simplified_chains": simplified_count, "crossing_reverted_chains": reverted_count},
            "original_osm_tag_columns": retained_tag_columns,
            "pruning": {
                "component_limit_ft": PRUNE_LENGTH_FEET, "boundary_margin_ft": BOUNDARY_MARGIN_FEET,
                "pruned_components": pruned_components, "pruned_edges": len(removed),
                "rule": "isolated unnamed service components strictly under 200 ft within the boundary inset",
                "by_action": {action: {"source_edges": count, "length_ft": length_by_action[action]} for action, count in sorted(count_by_action.items())},
                "osm_extraction": str(osm_extraction.resolve()) if osm_extraction is not None else None,
                "osm_classification": str(osm_classification.resolve()) if osm_classification is not None else None,
            },
            "counts": {"input_edges": len(edges), "output_edges": len(output_edges), "input_nodes": len(nodes), "output_nodes": len(output_nodes), "ledger_fragments": len(ledger)},
            "checks": {"source_hash_before_equals_after": True, "all_output_layers_reopened": True, "lengths_are_source_sums": True, "original_preserved": True},
        }
        (staging / REPORT_FILENAME).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staging.rename(destination)
    except Exception:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return report
