# 0006. Test tooling introduced with the first testable behavior

Status: Accepted
Date: 2026-10-29

Recorded retroactively.

## Context
The scaffold has no calculation or loader behavior. An empty test suite would report passing results that mean nothing.

## Decision
Use Vitest for unit and integration tests and Playwright for browser tests. Install neither until the first PR that adds behavior to test.

## Alternatives considered
- Install both now: produces an empty suite that could be mistaken for evidence.

## Consequences
Validation reports must not cite a test suite until one exists. Manual desktop, narrow-width, and keyboard review applies to UI changes until browser coverage exists.

## Revisit when
CI needs a browser smoke test earlier than the first testable behavior.
