# 0007. Preview hosting, relative base path, and deploy gating

Status: Accepted
Date: 2026-10-29

Recorded retroactively.

## Context
A reviewable preview is useful during development. The eventual host is CDOT-managed and may serve the application from a subdirectory.

## Decision
GitHub Pages hosts a public development preview from `main`. Deployment runs only after the `Verify foundation` job succeeds and deploys the verified artifact. The build uses relative asset paths so one build works at the Pages URL, a domain root, or a subdirectory. The page footer shows the build commit.

## Alternatives considered
- Separate Pages workflow: deployed in parallel with CI, so a failing check did not stop deployment.
- Absolute base path: needs a different build per host.

## Consequences
The preview is not CDOT staging or production and is not evidence for requirement R-01. The relative base must be confirmed on the CDOT host.

## Revisit when
CDOT hosting is established.
