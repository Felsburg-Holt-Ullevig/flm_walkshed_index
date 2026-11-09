from __future__ import annotations

import pytest

from flm_pipeline.census_normalize import NormalizationError, normalize_quartet


def test_zero_and_valid_estimate_with_missing_moe_are_preserved_independently() -> None:
    zero = normalize_quartet("0", "", "0", "")
    assert zero.estimate == 0
    assert zero.estimate_status == "valid"
    assert zero.moe == 0
    assert zero.moe_status == "valid"

    missing_moe = normalize_quartet("12", "", "", "")
    assert missing_moe.estimate == 12
    assert missing_moe.estimate_status == "valid"
    assert missing_moe.moe is None
    assert missing_moe.moe_status == "missing"


@pytest.mark.parametrize(
    ("token", "reason"),
    [
        ("-999999999", "insufficient_sample_or_unavailable"),
        ("-999999999.0", "insufficient_sample_or_unavailable"),
        ("-888888888.000", "not_applicable_or_available"),
        ("-666666666", "estimate_not_computable"),
        ("-555555555", "controlled_moe"),
        ("-333333333", "open_ended_median_interval"),
        ("-222222222", "moe_not_computable"),
    ],
)
def test_recognized_sentinels_become_null_with_reason(token: str, reason: str) -> None:
    result = normalize_quartet(token, "", "", "")
    assert result.estimate is None
    assert result.estimate_status == "sentinel"
    assert result.estimate_annotation is None
    assert result.estimate_detail == reason
    assert result.raw_estimate == token


def test_annotations_are_retained_and_not_parsed_as_counts() -> None:
    result = normalize_quartet("25", "*****", "N", "")
    assert result.estimate is None
    assert result.estimate_status == "annotated"
    assert result.estimate_annotation == "*****"
    assert result.moe is None
    assert result.moe_status == "annotated"
    assert result.moe_annotation == "N"
    assert result.raw_estimate_annotation == "*****"
    assert result.raw_moe == "N"


@pytest.mark.parametrize("annotation", ["UNKNOWN", "!", "A"])
def test_unknown_annotation_codes_fail(annotation: str) -> None:
    with pytest.raises(NormalizationError, match="unsupported annotation"):
        normalize_quartet("5", annotation, "2", "")


@pytest.mark.parametrize("token", ["-1", "1.5", "NaN", "Infinity", "not-a-number"])
def test_negative_fractional_nonfinite_and_unrecognized_values_fail(token: str) -> None:
    with pytest.raises(NormalizationError):
        normalize_quartet(token, "", "", "")


def test_null_and_blank_estimate_are_missing() -> None:
    assert normalize_quartet(None, "", "", "").estimate_status == "missing"
    assert normalize_quartet("  ", "", "", "").estimate_status == "missing"
