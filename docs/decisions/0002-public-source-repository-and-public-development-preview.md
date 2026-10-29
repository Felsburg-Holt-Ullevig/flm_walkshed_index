# 0002. Public source repository and public development preview

Status: Accepted
Date: 2026-10-29

Recorded retroactively.

## Context
The project needs shared development tooling and a reviewable preview. The repository and its GitHub Pages preview are public.

## Decision
Keep the source repository and the GitHub Pages development preview public.

## Alternatives considered
- Private repository with a public site: hides review history from outside reviewers but complicates sharing.
- Curated public export of a private repository: adds a second source of truth.

## Consequences
Tracked files, issues, and pull requests are public. Client documents, credentials, and restricted data stay outside the repository. `.gitignore` is not a secrecy mechanism and does not remove tracked history.

## Revisit when
Restricted material must accompany the code, or the client requires private development.
