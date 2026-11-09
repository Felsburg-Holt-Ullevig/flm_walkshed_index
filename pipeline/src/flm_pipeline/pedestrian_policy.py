"""Pure evaluator for the accepted experimental OSM pedestrian policy.

This module has no filesystem, GIS, environment, or global-state dependency.
Raw tag spelling and ordered source references are evaluated as supplied.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence


RULE_VERSION = "pedestrian-policy-0.3"
SCENARIO_ID = "public-walk-experiment-0.3"

INCLUDED_HIGHWAYS = frozenset({
    "footway", "pedestrian", "path", "steps", "living_street", "residential", "service",
    "unclassified", "track", "road", "tertiary", "tertiary_link", "secondary",
    "secondary_link", "primary", "primary_link",
})
LIMITED_HIGHWAYS = frozenset({"motorway", "motorway_link", "trunk", "trunk_link"})
LIFECYCLE_HIGHWAYS = frozenset({"construction", "proposed", "abandoned", "disused", "razed"})
UNCERTAIN_HIGHWAYS = frozenset({"cycleway", "bridleway"})
SOFT_BARRIERS = frozenset({
    "bollard", "cycle_barrier", "entrance", "gate", "lift_gate", "swing_gate",
    "kissing_gate", "stile", "turnstile",
})
HARD_BARRIERS = frozenset({"wall", "fence", "hedge", "retaining_wall", "block", "jersey_barrier"})
_ID_DIGITS = frozenset("0123456789")


class PolicyInputError(ValueError):
    """Raised when a caller supplies malformed canonical entity data."""


@dataclass(frozen=True)
class WayEvaluation:
    rule_version: str
    scenario_id: str
    entity_type: str
    osm_id: str
    eligibility: str
    direction: str
    proposed_direction: str
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    geometry_role: str
    sidewalk_general: str
    sidewalk_left: str
    sidewalk_right: str
    sidewalk_both: str
    unsupported_tag_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"reason_codes": list(self.reason_codes), "warnings": list(self.warnings), "unsupported_tag_keys": list(self.unsupported_tag_keys)}


@dataclass(frozen=True)
class NodeEvaluation:
    rule_version: str
    scenario_id: str
    entity_type: str
    osm_id: str
    disposition: str
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported_tag_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"reason_codes": list(self.reason_codes), "warnings": list(self.warnings), "unsupported_tag_keys": list(self.unsupported_tag_keys)}


@dataclass(frozen=True)
class _Access:
    disposition: str  # permit, prohibit, unknown, absent
    reason: str | None = None
    warning: str | None = None


def _validate_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value[0] == "0" or any(char not in _ID_DIGITS for char in value):
        raise PolicyInputError(f"{label} must be a positive decimal string without leading zeros")
    return value


def _validate_tags(value: Any, label: str = "tags") -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise PolicyInputError(f"{label} must be a string-to-string mapping")
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise PolicyInputError(f"{label} keys and values must be strings")
    return value


def _access(tags: Mapping[str, str], *, absent_is_neutral: bool) -> _Access:
    if "foot" in tags:
        prefix, value = "FOOT", tags["foot"]
    elif "access" in tags:
        prefix, value = "ACCESS", tags["access"]
    elif absent_is_neutral:
        return _Access("absent")
    else:
        return _Access("absent", "A_DEFAULT")
    if value in {"yes", "designated"}:
        return _Access("permit", f"A_{prefix}_ALLOW")
    if value == "permissive":
        return _Access("permit", f"A_{prefix}_PERMISSIVE", "W_REVOCABLE")
    if value in {"no", "private"}:
        return _Access("prohibit", f"A_{prefix}_DENY")
    return _Access("unknown", f"A_{prefix}_UNSUPPORTED")


def _unsupported_tags(tags: Mapping[str, str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    conditional: set[str] = set()
    variants: set[str] = set()
    for key in tags:
        if ":conditional" in key:
            conditional.add(key)
        if key.startswith("foot:") and key != "foot:conditional":
            variants.add(key)
        if key.startswith("access:") and key != "access:conditional":
            variants.add(key)
        if key.startswith("oneway:foot:") and key != "oneway:foot:conditional":
            variants.add(key)
        if key.startswith("oneway:") and key.endswith(":foot") and key != "oneway:foot":
            variants.add(key)
    return tuple(sorted(conditional)), tuple(sorted(variants))


def _sidewalk(value: str | None, *, side_specific: bool = False) -> str:
    if value is None:
        return "unknown"
    if side_specific:
        return {
            "yes": "present", "no": "explicit_none", "separate": "separately_mapped_asserted",
        }.get(value, "unsupported")
    return {
        "yes": "present_unspecified", "both": "both", "left": "left_only", "right": "right_only",
        "no": "explicit_none", "none": "explicit_none", "separate": "separately_mapped_asserted",
    }.get(value, "unsupported")


def _sidewalk_conflict(tags: Mapping[str, str], general: str, left: str, right: str) -> bool:
    """Flag direct side contradictions whose meaning is explicit in policy examples."""
    if general == "both" and (left == "explicit_none" or right == "explicit_none"):
        return True
    if general == "left_only" and (left == "explicit_none" or right == "present"):
        return True
    if general == "right_only" and (right == "explicit_none" or left == "present"):
        return True
    if general == "explicit_none" and (left == "present" or right == "present"):
        return True
    # sidewalk:both=yes is a both-sides assertion; no conflicts with an explicit
    # general one-side/no assertion. Other interactions remain separately recorded.
    both_value = tags.get("sidewalk:both")
    if both_value == "yes" and (
        general in {"left_only", "right_only", "explicit_none"}
        or left == "explicit_none"
        or right == "explicit_none"
    ):
        return True
    if both_value == "no" and (
        general == "both" or left == "present" or right == "present"
    ):
        return True
    return False


def _geometry_role(highway: str | None, tags: Mapping[str, str]) -> str:
    if highway == "footway":
        if tags.get("footway") == "sidewalk":
            return "sidewalk"
        if tags.get("footway") == "crossing":
            return "crossing"
        return "other_pedestrian"
    if highway in {"path", "steps", "pedestrian"}:
        return "other_pedestrian"
    if highway == "cycleway":
        return "cycleway"
    return "other"


def evaluate_way(osm_id: str, node_refs: Sequence[str], tags: Mapping[str, str]) -> WayEvaluation:
    """Evaluate one canonical way without geometry or side effects."""
    way_id = _validate_id(osm_id, "way osm_id")
    if not isinstance(node_refs, Sequence) or isinstance(node_refs, (str, bytes)):
        raise PolicyInputError("way node_refs must be an ordered sequence of ID strings")
    if len(node_refs) < 2:
        raise PolicyInputError("way node_refs must contain at least two references")
    for item in node_refs:
        _validate_id(item, "way node reference")
    raw_tags = _validate_tags(tags, "way tags")

    reasons: list[str] = []
    warnings: list[str] = []
    highway = raw_tags.get("highway")

    # Stage 1: source structure and unsupported highway classes.
    unsupported_structure = False
    supported_highways = INCLUDED_HIGHWAYS | LIMITED_HIGHWAYS | LIFECYCLE_HIGHWAYS | UNCERTAIN_HIGHWAYS
    if "highway" not in raw_tags or highway == "" or highway not in supported_highways:
        reasons.append("H_UNSUPPORTED")
    lifecycle_excluded = highway in LIFECYCLE_HIGHWAYS
    if lifecycle_excluded:
        reasons.append("H_LIFECYCLE")
    if ("area" in raw_tags and raw_tags["area"] != "no") or ("indoor" in raw_tags and raw_tags["indoor"] != "no") or "level" in raw_tags or "conveying" in raw_tags:
        unsupported_structure = True
        reasons.append("S_UNSUPPORTED_STRUCTURE")

    # Stage 2: foot-specific access overrides generic access, including unsupported values.
    access = _access(raw_tags, absent_is_neutral=False)
    if access.reason:
        reasons.append(access.reason)
    if access.warning:
        warnings.append(access.warning)

    # Stage 3: record class defaults when no supported explicit access decision exists.
    highway_disposition = "unknown"
    if lifecycle_excluded:
        highway_disposition = "exclude"
    elif access.disposition == "permit":
        if highway in supported_highways:
            highway_disposition = "include"
    elif access.disposition not in {"prohibit"}:
        if highway in INCLUDED_HIGHWAYS:
            highway_disposition = "include"
            reasons.append("H_DEFAULT_INCLUDE")
        elif highway in LIMITED_HIGHWAYS:
            highway_disposition = "exclude"
            reasons.append("H_LIMITED_ACCESS")
        elif highway in UNCERTAIN_HIGHWAYS:
            reasons.append("H_FOOT_UNCONFIRMED")
        elif "highway" not in raw_tags or highway == "" or highway not in supported_highways:
            reasons.append("H_UNSUPPORTED")

    if highway == "steps":
        warnings.append("W_STEPS")
    if highway == "road":
        warnings.append("W_ROAD_CLASS")

    # Stage 4: conditionals and unimplemented mode/direction variants stay unresolved.
    conditional_keys, variant_keys = _unsupported_tags(raw_tags)
    if conditional_keys:
        reasons.append("A_CONDITIONAL_UNRESOLVED")
    if variant_keys:
        reasons.append("A_VARIANT_UNSUPPORTED")

    # Stage 5: pedestrian direction; generic vehicle direction is ignored.
    foot_oneway = raw_tags.get("oneway:foot")
    if foot_oneway is None or foot_oneway == "no":
        proposed_direction = "both"
        reasons.append("D_BOTH")
    elif foot_oneway == "yes":
        proposed_direction = "forward"
        reasons.append("D_FORWARD")
    elif foot_oneway == "-1":
        proposed_direction = "reverse"
        reasons.append("D_REVERSE")
    else:
        proposed_direction = "unknown"
        reasons.append("D_UNSUPPORTED")
    if "oneway" in raw_tags or ("junction" in raw_tags and raw_tags.get("junction") == "roundabout"):
        warnings.append("W_VEHICLE_ONEWAY_IGNORED")

    if access.disposition == "prohibit" or highway_disposition == "exclude" or lifecycle_excluded:
        eligibility = "exclude"
        direction = "none"
    elif unsupported_structure or access.disposition == "unknown" or highway_disposition == "unknown" or conditional_keys or variant_keys or proposed_direction == "unknown":
        eligibility = "unknown"
        direction = "unknown"
    else:
        eligibility = "include"
        direction = proposed_direction

    geometry_role = _geometry_role(highway, raw_tags)
    if raw_tags.get("footway") == "sidewalk" and highway != "footway":
        warnings.append("W_SIDEWALK_CONFLICT")
    sidewalk_general = _sidewalk(raw_tags.get("sidewalk"))
    sidewalk_left = _sidewalk(raw_tags.get("sidewalk:left"), side_specific=True)
    sidewalk_right = _sidewalk(raw_tags.get("sidewalk:right"), side_specific=True)
    sidewalk_both = _sidewalk(raw_tags.get("sidewalk:both"), side_specific=True)
    if _sidewalk_conflict(raw_tags, sidewalk_general, sidewalk_left, sidewalk_right):
        warnings.append("W_SIDEWALK_CONFLICT")

    return WayEvaluation(
        RULE_VERSION, SCENARIO_ID, "way", way_id, eligibility, direction, proposed_direction,
        tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(warnings)), geometry_role,
        sidewalk_general, sidewalk_left, sidewalk_right, sidewalk_both,
        tuple(sorted(set(conditional_keys) | set(variant_keys))),
    )


def evaluate_node(osm_id: str, tags: Mapping[str, str]) -> NodeEvaluation:
    """Evaluate one referenced source node's access and barrier evidence."""
    node_id = _validate_id(osm_id, "node osm_id")
    raw_tags = _validate_tags(tags, "node tags")
    reasons: list[str] = []
    warnings: list[str] = []
    access = _access(raw_tags, absent_is_neutral=True)
    if access.reason:
        reasons.append(access.reason)
    if access.warning:
        warnings.append(access.warning)
    conditional_keys, variant_keys = _unsupported_tags(raw_tags)
    if conditional_keys:
        reasons.append("A_CONDITIONAL_UNRESOLVED")
    if variant_keys:
        reasons.append("A_VARIANT_UNSUPPORTED")

    barrier = raw_tags.get("barrier")
    locked = raw_tags.get("locked")
    barrier_unknown = False
    blocked = access.disposition == "prohibit"
    if blocked:
        reasons.append("B_ACCESS_BLOCK")
    if barrier in HARD_BARRIERS:
        blocked = True
        reasons.append("B_PHYSICAL_BLOCK")
    elif barrier is None or barrier == "no":
        reasons.append("B_PASS")
    elif barrier == "kerb":
        # General pedestrian traversal; raw curb/accessibility evidence is retained.
        reasons.append("B_KERB_PASS")
    elif barrier in SOFT_BARRIERS:
        if access.disposition == "permit":
            reasons.append("B_PERMISSION_PASS")
            warnings.append("W_BARRIER_UNVERIFIED")
        elif access.disposition == "prohibit":
            barrier_unknown = True
            reasons.append("B_UNRESOLVED")
        else:
            barrier_unknown = True
            reasons.append("B_UNRESOLVED")
    else:
        barrier_unknown = True
        reasons.append("B_UNRESOLVED")

    locked_unknown = False
    if locked == "yes":
        blocked = True
        reasons.append("B_LOCKED")
    elif locked is not None and locked != "no":
        locked_unknown = True
        reasons.append("B_LOCK_UNRESOLVED")

    restriction_unknown = access.disposition == "unknown" or bool(conditional_keys) or bool(variant_keys)
    if blocked:
        disposition = "block"
    elif barrier_unknown or locked_unknown or restriction_unknown:
        disposition = "unknown"
    else:
        disposition = "pass"
    return NodeEvaluation(
        RULE_VERSION, SCENARIO_ID, "node", node_id, disposition,
        tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(warnings)),
        tuple(sorted(set(conditional_keys) | set(variant_keys))),
    )
