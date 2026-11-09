# Data and service adapters

Place GIS-service access, prepared-package loading, import/export, and storage implementations here when introduced. Validate external input at the boundary and translate it into the domain's types. Keep service-specific payloads out of authoritative calculations.

Coverage, pagination, incomplete responses, cancellation, schema/version compatibility, and failures need explicit behavior. No adapter or external endpoint is configured in the foundation. See [data contract](../../docs/data-contract.md).

Implemented network loading: `network-package.ts` validates shared schemas and cross-file invariants before exposing pure graph inputs. `generated/` types derive from the schema sources and are checked with `pnpm schema:check`. `traverse.ts` coordinates a cancellable worker; `reachable-result.ts` binds computed output to the validated manifest. See `pipeline/browser-network-review.md`.
