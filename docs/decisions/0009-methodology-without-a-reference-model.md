# 0009. Methodology without a reference model

Status: Accepted
Date: 2026-10-29

Recorded retroactively.

## Context
The original ArcGIS model is unavailable, so the method cannot be reproduced from it.

## Decision
Specify the method in `docs/methodology.md`, have it approved by the methodology approver and CDOT reviewers, and verify it against hand calculations, an independent GIS or Python reproduction of sample areas, and expert map review.

## Alternatives considered
- Reverse-engineer the original model from published outputs: outputs alone do not define the method.

## Consequences
The method specification is itself a deliverable. No "match the original" acceptance criterion exists. Benchmark evidence follows the rules in `docs/validation.md`.

## Revisit when
The original model or its outputs become available.
