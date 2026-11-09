"""Pure parsing for the proposed ACS estimate/MOE quartets.

The mapping is deliberately versioned and must remain behind the accepted
experiment check in ``census_sample`` until a data owner approves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .census_spec import NORMALIZATION_VERSION


class NormalizationError(ValueError):
    """Raised when an ACS quartet contains an unsupported representation."""


SENTINELS = {
    Decimal("-999999999"): "insufficient_sample_or_unavailable",
    Decimal("-888888888"): "not_applicable_or_available",
    Decimal("-666666666"): "estimate_not_computable",
    Decimal("-555555555"): "controlled_moe",
    Decimal("-333333333"): "open_ended_median_interval",
    Decimal("-222222222"): "moe_not_computable",
}
ANNOTATIONS = frozenset({"N", "(X)", "-", "**", "***", "*****", "+", "*", "c"})


@dataclass(frozen=True)
class NormalizedQuartet:
    raw_estimate: str | None
    raw_estimate_annotation: str | None
    raw_moe: str | None
    raw_moe_annotation: str | None
    estimate: int | None
    estimate_status: str
    estimate_annotation: str | None
    estimate_detail: str | None
    moe: int | None
    moe_status: str
    moe_annotation: str | None
    moe_detail: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_estimate": self.raw_estimate,
            "raw_estimate_annotation": self.raw_estimate_annotation,
            "raw_moe": self.raw_moe,
            "raw_moe_annotation": self.raw_moe_annotation,
            "estimate": self.estimate,
            "estimate_status": self.estimate_status,
            "estimate_annotation": self.estimate_annotation,
            "estimate_detail": self.estimate_detail,
            "moe": self.moe,
            "moe_status": self.moe_status,
            "moe_annotation": self.moe_annotation,
            "moe_detail": self.moe_detail,
        }


def _raw(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise NormalizationError(f"{field} must be a string or null")
    return value


def _annotation(value: str | None, field: str) -> str | None:
    if value is None or value.strip() == "":
        return None
    code = value.strip()
    if code not in ANNOTATIONS:
        raise NormalizationError(f"{field} contains an unsupported annotation code")
    return code


def _count(value: str | None, annotation: str | None, label: str) -> tuple[int | None, str, str | None, str | None]:
    if value is None or value.strip() == "":
        return None, "missing", annotation, None
    token = value.strip()
    if annotation is not None:
        return None, "annotated", annotation, None
    if token in ANNOTATIONS:
        return None, "annotated", token, None
    try:
        number = Decimal(token)
    except InvalidOperation as error:
        raise NormalizationError(f"{label} is neither a count nor a recognized annotation") from error
    if not number.is_finite():
        raise NormalizationError(f"{label} must be finite")
    if number in SENTINELS:
        return None, "sentinel", None, SENTINELS[number]
    if number < 0 or number != number.to_integral_value():
        raise NormalizationError(f"{label} must be a nonnegative whole-number count")
    return int(number), "valid", annotation, None


def normalize_quartet(
    estimate: object,
    estimate_annotation: object,
    moe: object,
    moe_annotation: object,
) -> NormalizedQuartet:
    """Retain all four raw tokens and parse estimate/MOE independently."""
    raw_estimate = _raw(estimate, "estimate")
    raw_estimate_annotation = _raw(estimate_annotation, "estimate annotation")
    raw_moe = _raw(moe, "MOE")
    raw_moe_annotation = _raw(moe_annotation, "MOE annotation")

    estimate_code = _annotation(raw_estimate_annotation, "estimate annotation")
    moe_code = _annotation(raw_moe_annotation, "MOE annotation")
    estimate_value, estimate_status, estimate_annotation_value, estimate_detail = _count(raw_estimate, estimate_code, "estimate")
    moe_value, moe_status, moe_annotation_value, moe_detail = _count(raw_moe, moe_code, "MOE")
    return NormalizedQuartet(
        raw_estimate,
        raw_estimate_annotation,
        raw_moe,
        raw_moe_annotation,
        estimate_value,
        estimate_status,
        estimate_annotation_value,
        estimate_detail,
        moe_value,
        moe_status,
        moe_annotation_value,
        moe_detail,
    )
