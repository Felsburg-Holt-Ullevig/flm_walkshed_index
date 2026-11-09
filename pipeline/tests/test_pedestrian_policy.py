from __future__ import annotations

from collections.abc import Mapping

import pytest

from flm_pipeline.pedestrian_policy import (
    INCLUDED_HIGHWAYS,
    LIFECYCLE_HIGHWAYS,
    LIMITED_HIGHWAYS,
    SOFT_BARRIERS,
    HARD_BARRIERS,
    UNCERTAIN_HIGHWAYS,
    PolicyInputError,
    evaluate_node,
    evaluate_way,
)


def way(tags: Mapping[str, str] | None = None, refs: tuple[str, ...] = ("1", "2")):
    return evaluate_way("100", refs, tags or {"highway": "residential"})


@pytest.mark.parametrize("highway", sorted(INCLUDED_HIGHWAYS))
def test_all_default_included_highways(highway: str) -> None:
    result = way({"highway": highway})
    assert result.eligibility == "include"
    assert "H_DEFAULT_INCLUDE" in result.reason_codes


@pytest.mark.parametrize("highway", sorted(LIMITED_HIGHWAYS))
def test_limited_access_highways_default_to_exclude(highway: str) -> None:
    result = way({"highway": highway})
    assert result.eligibility == "exclude"
    assert "H_LIMITED_ACCESS" in result.reason_codes


@pytest.mark.parametrize("highway", sorted(LIFECYCLE_HIGHWAYS))
def test_lifecycle_classes_exclude_even_with_foot_permission(highway: str) -> None:
    result = way({"highway": highway, "foot": "yes"})
    assert result.eligibility == "exclude"
    assert "H_LIFECYCLE" in result.reason_codes


@pytest.mark.parametrize("highway", sorted(UNCERTAIN_HIGHWAYS))
def test_cycleway_and_bridleway_need_explicit_permission(highway: str) -> None:
    assert way({"highway": highway}).eligibility == "unknown"
    assert way({"highway": highway, "foot": "designated"}).eligibility == "include"


@pytest.mark.parametrize("highway", ["", "elevator", "corridor", "platform", "busway", "bus_guideway", "escape", "raceway", "unknown"])
def test_unsupported_highway_values_remain_unknown(highway: str) -> None:
    result = way({"highway": highway, "foot": "yes"})
    assert result.eligibility == "unknown"
    assert "H_UNSUPPORTED" in result.reason_codes


def test_missing_highway_is_unknown_even_with_permission() -> None:
    result = way({"foot": "yes"})
    assert result.eligibility == "unknown"
    assert "H_UNSUPPORTED" in result.reason_codes


@pytest.mark.parametrize(
    ("key", "value", "eligibility", "reason"),
    [
        ("foot", "yes", "include", "A_FOOT_ALLOW"),
        ("foot", "designated", "include", "A_FOOT_ALLOW"),
        ("foot", "permissive", "include", "A_FOOT_PERMISSIVE"),
        ("foot", "no", "exclude", "A_FOOT_DENY"),
        ("foot", "private", "exclude", "A_FOOT_DENY"),
        ("foot", "use_sidepath", "unknown", "A_FOOT_UNSUPPORTED"),
        ("foot", "destination", "unknown", "A_FOOT_UNSUPPORTED"),
        ("foot", "customers", "unknown", "A_FOOT_UNSUPPORTED"),
        ("foot", "delivery", "unknown", "A_FOOT_UNSUPPORTED"),
        ("foot", "agricultural", "unknown", "A_FOOT_UNSUPPORTED"),
        ("foot", "forestry", "unknown", "A_FOOT_UNSUPPORTED"),
        ("foot", "other", "unknown", "A_FOOT_UNSUPPORTED"),
        ("foot", "", "unknown", "A_FOOT_UNSUPPORTED"),
        ("foot", "YES", "unknown", "A_FOOT_UNSUPPORTED"),
        ("access", "yes", "include", "A_ACCESS_ALLOW"),
        ("access", "designated", "include", "A_ACCESS_ALLOW"),
        ("access", "permissive", "include", "A_ACCESS_PERMISSIVE"),
        ("access", "no", "exclude", "A_ACCESS_DENY"),
        ("access", "private", "exclude", "A_ACCESS_DENY"),
        ("access", "destination", "unknown", "A_ACCESS_UNSUPPORTED"),
        ("access", "customers", "unknown", "A_ACCESS_UNSUPPORTED"),
        ("access", "delivery", "unknown", "A_ACCESS_UNSUPPORTED"),
        ("access", "agricultural", "unknown", "A_ACCESS_UNSUPPORTED"),
        ("access", "forestry", "unknown", "A_ACCESS_UNSUPPORTED"),
        ("access", "use_sidepath", "unknown", "A_ACCESS_UNSUPPORTED"),
        ("access", "other", "unknown", "A_ACCESS_UNSUPPORTED"),
        ("access", "", "unknown", "A_ACCESS_UNSUPPORTED"),
        ("access", "YES", "unknown", "A_ACCESS_UNSUPPORTED"),
    ],
)
def test_access_truth_table(key: str, value: str, eligibility: str, reason: str) -> None:
    result = way({"highway": "residential", key: value})
    assert result.eligibility == eligibility
    assert reason in result.reason_codes
    assert ("W_REVOCABLE" in result.warnings) == (value == "permissive")


def test_foot_precedence_and_explicit_permission_overrides() -> None:
    assert way({"highway": "residential", "foot": "yes", "access": "private"}).eligibility == "include"
    assert way({"highway": "residential", "foot": "no", "access": "yes"}).eligibility == "exclude"
    assert way({"highway": "residential", "foot": "unsupported", "access": "no"}).eligibility == "unknown"
    assert way({"highway": "motorway", "access": "yes"}).eligibility == "include"
    assert way({"highway": "trunk", "foot": "designated"}).eligibility == "include"


@pytest.mark.parametrize(
    ("value", "direction", "reason"),
    [(None, "both", "D_BOTH"), ("no", "both", "D_BOTH"), ("yes", "forward", "D_FORWARD"), ("-1", "reverse", "D_REVERSE"), ("true", "unknown", "D_UNSUPPORTED"), ("", "unknown", "D_UNSUPPORTED")],
)
def test_pedestrian_direction_table(value: str | None, direction: str, reason: str) -> None:
    tags = {"highway": "residential"}
    if value is not None:
        tags["oneway:foot"] = value
    result = way(tags)
    assert result.direction == direction
    assert reason in result.reason_codes


def test_generic_oneway_is_ignored_and_reported() -> None:
    result = way({"highway": "residential", "oneway": "yes", "junction": "roundabout"})
    assert result.direction == "both"
    assert "W_VEHICLE_ONEWAY_IGNORED" in result.warnings


@pytest.mark.parametrize("tags", [
    {"highway": "residential", "area": "yes"},
    {"highway": "residential", "area": ""},
    {"highway": "residential", "indoor": "yes"},
    {"highway": "residential", "indoor": ""},
    {"highway": "residential", "level": ""},
    {"highway": "residential", "conveying": "no"},
])
def test_unsupported_structure_is_unknown(tags: dict[str, str]) -> None:
    assert way(tags).eligibility == "unknown"


def test_decisive_access_exclusion_dominates_unsupported_structure() -> None:
    result = way({"highway": "residential", "area": "yes", "foot": "no"})
    assert result.eligibility == "exclude"
    assert "S_UNSUPPORTED_STRUCTURE" in result.reason_codes


@pytest.mark.parametrize("key", [
    "foot:conditional", "access:conditional", "oneway:conditional",
    "oneway:foot:conditional", "maxspeed:conditional",
])
def test_conditional_fields_are_reported_without_parsing(key: str) -> None:
    result = way({"highway": "residential", "foot": "yes", key: ""})
    assert result.eligibility == "unknown"
    assert "A_CONDITIONAL_UNRESOLVED" in result.reason_codes
    assert key in result.unsupported_tag_keys


@pytest.mark.parametrize("key", ["foot:forward", "foot:backward", "access:lanes", "oneway:foot:forward", "oneway:vehicle:foot"])
def test_unimplemented_access_and_direction_variants_are_unknown(key: str) -> None:
    result = way({"highway": "residential", "foot": "yes", key: "no"})
    assert result.eligibility == "unknown"
    assert "A_VARIANT_UNSUPPORTED" in result.reason_codes


@pytest.mark.parametrize("barrier", sorted(SOFT_BARRIERS))
def test_soft_barriers_need_explicit_permission(barrier: str) -> None:
    assert evaluate_node("1", {"barrier": barrier}).disposition == "unknown"
    permitted = evaluate_node("1", {"barrier": barrier, "foot": "yes"})
    assert permitted.disposition == "pass"
    assert "B_PERMISSION_PASS" in permitted.reason_codes
    assert "W_BARRIER_UNVERIFIED" in permitted.warnings


@pytest.mark.parametrize("barrier", sorted(HARD_BARRIERS))
def test_physical_barriers_block_even_with_permission(barrier: str) -> None:
    result = evaluate_node("1", {"barrier": barrier, "foot": "yes"})
    assert result.disposition == "block"
    assert "B_PHYSICAL_BLOCK" in result.reason_codes


@pytest.mark.parametrize("barrier", ["", "unknown", "gatehouse", "bollards"])
def test_other_barrier_values_remain_unknown_even_with_permission(barrier: str) -> None:
    result = evaluate_node("1", {"barrier": barrier, "foot": "yes"})
    assert result.disposition == "unknown"
    assert "B_UNRESOLVED" in result.reason_codes


@pytest.mark.parametrize("kerb", [None, "flush", "lowered", "raised", "rolled", "unknown", "", "other"])
@pytest.mark.parametrize("wheelchair", [None, "yes", "no"])
def test_kerbs_allow_general_pedestrian_travel_without_accessibility_inference(kerb, wheelchair):
    tags = {"barrier": "kerb"}
    if kerb is not None:
        tags["kerb"] = kerb
    if wheelchair is not None:
        tags["wheelchair"] = wheelchair
    original = tags.copy()
    result = evaluate_node("1", tags)
    assert result.disposition == "pass"
    assert "B_KERB_PASS" in result.reason_codes
    assert "B_UNRESOLVED" not in result.reason_codes
    assert tags == original


@pytest.mark.parametrize("extra,expected", [
    ({"foot": "no"}, "block"), ({"access": "private"}, "block"),
    ({"locked": "yes"}, "block"), ({"foot": "destination"}, "unknown"),
    ({"foot:conditional": "no @ (Mo-Fr)"}, "unknown"),
    ({"locked": "unknown"}, "unknown"),
])
def test_kerb_does_not_override_other_restrictions(extra, expected):
    assert evaluate_node("1", {"barrier": "kerb", **extra}).disposition == expected


def test_kerb_spelling_is_exact():
    assert evaluate_node("1", {"barrier": "Kerb"}).disposition == "unknown"


@pytest.mark.parametrize(("tags", "disposition", "reason"), [
    ({}, "pass", "B_PASS"),
    ({"barrier": "no"}, "pass", "B_PASS"),
    ({"locked": "yes"}, "block", "B_LOCKED"),
    ({"locked": "no"}, "pass", "B_PASS"),
    ({"locked": ""}, "unknown", "B_LOCK_UNRESOLVED"),
    ({"locked": "true"}, "unknown", "B_LOCK_UNRESOLVED"),
    ({"foot": "no"}, "block", "B_ACCESS_BLOCK"),
    ({"access": "no"}, "block", "B_ACCESS_BLOCK"),
    ({"barrier": "gate", "foot": "no"}, "block", "B_ACCESS_BLOCK"),
    ({"access:conditional": "no @ (Mo-Fr)"}, "unknown", "A_CONDITIONAL_UNRESOLVED"),
    ({"barrier": "gate", "foot": "yes", "locked": "yes"}, "block", "B_LOCKED"),
])
def test_node_access_lock_and_barrier_precedence(tags: dict[str, str], disposition: str, reason: str) -> None:
    result = evaluate_node("1", tags)
    assert result.disposition == disposition
    assert reason in result.reason_codes


@pytest.mark.parametrize(("value", "expected"), [
    (None, "unknown"), ("yes", "present_unspecified"), ("both", "both"), ("left", "left_only"),
    ("right", "right_only"), ("no", "explicit_none"), ("none", "explicit_none"),
    ("separate", "separately_mapped_asserted"), ("YES", "unsupported"), ("", "unsupported"),
])
def test_general_sidewalk_evidence_values(value: str | None, expected: str) -> None:
    tags = {"highway": "residential"}
    if value is not None:
        tags["sidewalk"] = value
    result = way(tags)
    assert result.eligibility == "include"
    assert result.sidewalk_general == expected


@pytest.mark.parametrize(("value", "expected"), [
    (None, "unknown"), ("yes", "present"), ("no", "explicit_none"),
    ("separate", "separately_mapped_asserted"), ("both", "unsupported"), ("", "unsupported"),
])
def test_side_specific_sidewalk_evidence_values(value: str | None, expected: str) -> None:
    tags = {"highway": "residential"}
    if value is not None:
        tags["sidewalk:left"] = value
    result = way(tags)
    assert result.sidewalk_left == expected
    assert result.eligibility == "include"


@pytest.mark.parametrize(("key", "value", "expected"), [
    ("sidewalk:left", "yes", "present"),
    ("sidewalk:left", "no", "explicit_none"),
    ("sidewalk:left", "separate", "separately_mapped_asserted"),
    ("sidewalk:left", "both", "unsupported"),
    ("sidewalk:right", "yes", "present"),
    ("sidewalk:right", "no", "explicit_none"),
    ("sidewalk:right", "separate", "separately_mapped_asserted"),
    ("sidewalk:right", "", "unsupported"),
    ("sidewalk:both", "yes", "present"),
    ("sidewalk:both", "no", "explicit_none"),
    ("sidewalk:both", "separate", "separately_mapped_asserted"),
    ("sidewalk:both", "left", "unsupported"),
])
def test_each_sidewalk_side_tag_uses_the_reviewed_value_vocabulary(key: str, value: str, expected: str) -> None:
    result = way({"highway": "residential", key: value})
    field = key.replace("sidewalk:", "sidewalk_")
    assert getattr(result, field) == expected


def test_unknown_tag_on_limited_access_way_does_not_override_class_exclusion() -> None:
    result = way({"highway": "trunk", "access": "destination"})
    assert result.eligibility == "exclude"
    assert "A_ACCESS_UNSUPPORTED" in result.reason_codes
    assert "H_LIMITED_ACCESS" in result.reason_codes


def test_known_foot_exclusion_dominates_conditional_uncertainty() -> None:
    result = way({"highway": "residential", "foot": "no", "access:conditional": ""})
    assert result.eligibility == "exclude"
    assert "A_FOOT_DENY" in result.reason_codes
    assert "A_CONDITIONAL_UNRESOLVED" in result.reason_codes


def test_known_node_exclusion_keeps_unresolved_gate_evidence() -> None:
    result = evaluate_node("1", {"barrier": "gate", "foot": "no"})
    assert result.disposition == "block"
    assert "B_ACCESS_BLOCK" in result.reason_codes
    assert "B_UNRESOLVED" in result.reason_codes


@pytest.mark.parametrize(("highway", "footway", "role"), [
    ("footway", "sidewalk", "sidewalk"), ("footway", "crossing", "crossing"),
    ("footway", "access_aisle", "other_pedestrian"), ("path", "", "other_pedestrian"),
    ("steps", "", "other_pedestrian"), ("pedestrian", "", "other_pedestrian"),
    ("cycleway", "", "cycleway"), ("residential", "", "other"),
])
def test_geometry_roles(highway: str, footway: str, role: str) -> None:
    tags = {"highway": highway}
    if footway:
        tags["footway"] = footway
    assert way(tags).geometry_role == role


def test_reviewed_sidewalk_conflict_and_no_sidewalk_does_not_block_access() -> None:
    result = way({"highway": "residential", "sidewalk": "both", "sidewalk:left": "no"})
    assert result.eligibility == "include"
    assert result.sidewalk_general == "both"
    assert result.sidewalk_left == "explicit_none"
    assert "W_SIDEWALK_CONFLICT" in result.warnings
    conflicting_both = way({"highway": "residential", "sidewalk": "both", "sidewalk:both": "no"})
    assert "W_SIDEWALK_CONFLICT" in conflicting_both.warnings


def test_step_and_road_warnings_are_audit_only() -> None:
    assert "W_STEPS" in way({"highway": "steps"}).warnings
    assert "W_ROAD_CLASS" in way({"highway": "road"}).warnings


def test_results_are_deterministic_and_do_not_mutate_raw_inputs() -> None:
    tags = {"highway": "residential", "foot": "permissive", "sidewalk": "left"}
    original = tags.copy()
    first = way(tags)
    second = way(tags)
    assert first == second
    assert tags == original


@pytest.mark.parametrize("osm_id", ["", "0", "01", "-1", 1])
def test_invalid_way_ids_fail_validation(osm_id: object) -> None:
    with pytest.raises(PolicyInputError):
        evaluate_way(osm_id, ("1", "2"), {"highway": "residential"})  # type: ignore[arg-type]


def test_invalid_tags_and_too_short_way_fail_validation() -> None:
    with pytest.raises(PolicyInputError):
        evaluate_way("1", ("1",), {"highway": "residential"})
    with pytest.raises(PolicyInputError):
        evaluate_way("1", ("1", "2"), {"highway": 5})  # type: ignore[dict-item]
