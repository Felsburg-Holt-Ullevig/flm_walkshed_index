# 0003. Frontend toolchain

Status: Accepted
Date: 2026-10-29

Recorded retroactively.

## Context
The application is a static browser application that must be buildable and hostable without a server.

## Decision
Use React, strict TypeScript, and a Vite static build on Node 24 LTS, with pnpm 11, exact dependency versions, and one lockfile.

## Alternatives considered
- npm: simpler default; pnpm was chosen for strict, fast installs and existing team use.
- Other frameworks: no need shown.

## Consequences
Versions are recorded in `package.json` and `.node-version` and enforced at install time (`engineStrict`). Major runtime upgrades are reviewed changes.

## Revisit when
A major Node LTS change occurs, or the toolchain blocks a requirement.
