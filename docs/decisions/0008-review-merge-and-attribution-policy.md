# 0008. Review, merge, and attribution policy

Status: Accepted
Date: 2026-10-29

Recorded retroactively.

## Context
Work is performed largely by coding agents under human direction, and several people hold organization roles.

## Decision
The project lead approves contributions from other developers; the lead's own pull requests merge after CI passes; agents do not merge. Two rulesets on `main` implement this: CI and safety (no bypass) and review (repository admins may bypass on pull requests only). AI assistance is disclosed once in the README. Commits and pull requests carry no tool or model trailers. Commits use GitHub noreply identities.

## Alternatives considered
- Require a second approval on every PR: no second reviewer is routinely available.
- Per-commit AI attribution trailers: adds noise to history; one disclosure covers the project.

## Consequences
Organization owners can also bypass the review ruleset, so review of their pull requests is a team convention unless their organization role changes.

## Revisit when
FHU or CDOT adopts an AI-disclosure policy requiring more, or the team grows.
