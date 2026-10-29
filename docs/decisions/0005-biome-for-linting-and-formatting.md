# 0005. Biome for linting and formatting

Status: Accepted
Date: 2026-10-29

Recorded retroactively.

## Context
The project needs linting, formatting, accessibility rules, and an enforceable boundary that keeps `src/domain/` independent of UI code.

## Decision
Use Biome 2.x with the recommended preset (which includes accessibility rules) and an import restriction on `src/domain/`. Markdown is excluded from formatting.

## Alternatives considered
- ESLint with typescript-eslint and Prettier: more plugins, two tools, and a dependency on the TypeScript compiler API.

## Consequences
One tool and one configuration (`biome.json`). The `biome migrate` command must not be run on the configuration because it can change `"preset": "recommended"` to `"none"`, which disables every recommended rule.

## Revisit when
A needed rule exists only for ESLint.
