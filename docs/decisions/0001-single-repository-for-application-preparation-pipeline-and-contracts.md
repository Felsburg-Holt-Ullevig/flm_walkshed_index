# 0001. Single repository for application, preparation pipeline, and contracts

Status: Accepted
Date: 2026-10-29

Recorded retroactively.

## Context
The application and the offline data preparation pipeline share data contracts and are owned by one team.

## Decision
Keep the application, the preparation pipeline (`pipeline/`), and the contract documentation in one repository while one team owns both.

## Alternatives considered
- Separate application and pipeline repositories: adds coordination cost before a second owner exists.
- Git submodules: fragile for contributors and agents; avoid.

## Consequences
Contract changes and the code that uses them land in one reviewed PR. Large raw inputs stay outside Git, so repository size depends on discipline about fixtures.

## Revisit when
The pipeline needs different access, maintainers, or refresh cadence, or serves several applications.
