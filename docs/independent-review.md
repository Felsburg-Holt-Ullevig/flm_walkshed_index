# Independent review guide

Review source-to-result correctness, input validation, numerical assumptions, reproducibility and clarity. Treat recorded successful runs as claims to verify. Report concrete findings with severity, file/line or artifact evidence, practical impact and proposed remedy. Separate checks you ran from historical evidence and checks not run. Start read-only and preserve unrelated work; do not regenerate expected values or change source pins to clear failures.

## Read first

1. [Repository rules](../AGENTS.md), [architecture](../architecture_overview.md), [developer setup](../DEVELOPER.md), [requirements](requirements.md), [methodology](methodology.md), [data contracts](data-contract.md) and [validation](validation.md).
2. [Pedestrian policy](../pipeline/pedestrian-policy.md), [graph contract](../pipeline/routing-graph-contract.md), [routing references](../pipeline/routing-reference-spec.md), [network package schemas](../contracts/network-package/v1/README.md).
3. [Census specification](../pipeline/census-variable-spec.md), [spatial specification](../pipeline/spatial-allocation-spec.md), [allocation contract](../contracts/allocation-experiment/v1/README.md).

## Implementation and evidence

Inspect `pipeline/src/flm_pipeline/` for source extraction, policy, graph, routing, Census and geometry adapters; `pipeline/tools/package_network.py` and `run_spatial_experiment.py` for packaging/execution; `src/domain/` for pure traversal/allocation; `src/adapters/` and `src/workers/` for loading and worker boundaries. Examine fixtures and tests under `pipeline/fixtures/`, `pipeline/tests/`, `pipeline/tools/tests/`, domain/adapter test files and `tests/browser/`. Ask whether expected numbers are independent of implementation.

Run the [validation commands](validation.md) and [browser fixture procedure](../pipeline/browser-network-review.md). A clone includes synthetic fixtures, not regional sources, caches, local acceptance configs or generated outputs. Local review packets are deliberately excluded. A full regional audit requires a separately supplied evidence set; do not claim to reproduce those runs from the public clone alone. Never request an API key for cached or synthetic checks. Do not upload local material automatically.

## Review questions

- Do original node IDs preserve junctions without joining coincident or grade-separated crossings?
- Do direction, costs, budgets and partial segments follow the declared rules?
- Can stale, corrupt or mixed files pass runtime validation?
- Are Census fields, years, geography, joins, missingness and uncertainty interpreted correctly?
- Do area/point weighting and union-before-unique totals match independent examples?
- Are corridor spillover, gaps, rural sensitivity and incomplete coverage visible?
- Does the browser preserve state on failure and cancellation, and are synthetic capacity claims kept separate from regional evidence?
- Can a maintainer follow commands without hidden local files? Identify optional historical tools that require local evidence.

Return a plain-language assessment, prioritized findings, independently checked evidence, unresolved decisions and a bounded next task. Full coverage, station/point snapping implementation, allocated uncertainty and scoring remain separate work.
