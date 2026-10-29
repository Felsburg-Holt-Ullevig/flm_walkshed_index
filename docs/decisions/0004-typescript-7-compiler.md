# 0004. TypeScript 7 compiler

Status: Accepted
Date: 2026-10-29

Recorded retroactively.

## Context
TypeScript 7 provides the native compiler, which gives faster checks. The language is unchanged.

## Decision
Use TypeScript 7 for typechecking.

## Alternatives considered
- TypeScript 6: slower checks and no advantage for this project.

## Consequences
Tools that depend on the compiler's internal API may lag behind. Biome does not depend on it. If a required tool is incompatible, pin TypeScript 6 in `package.json`; no source changes are needed.

## Revisit when
The project adopts any tool that integrates with the TypeScript compiler (for example a test runner plugin or a map library's type tooling).
