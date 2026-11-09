import type { reachable } from '../domain/reachability';
import { type LoadedPackage, validateSchema } from './network-package';
export function bindResult(
  loaded: LoadedPackage,
  origin: string,
  budget: number,
  outputs: ReturnType<typeof reachable>,
) {
  const synthetic = loaded.manifest.coverage.readiness === 'synthetic_closed';
  const result = {
    schema_version: 'flm-reachable-1',
    release_id: loaded.manifest.release_id,
    graph_id: loaded.manifest.graph_id,
    manifest_sha256: loaded.manifestHash,
    app_version: '0.1.0',
    app_commit: __APP_COMMIT__,
    algorithm_version: 'experimental-reachability-1',
    request: {
      request_id: 'one-station-1',
      origin_mode: 'source_node',
      node_id: origin,
      entrance_verification: synthetic ? 'synthetic' : 'not_verified',
      time_budget_seconds: budget,
      access_seconds: 0,
    },
    computation_status:
      outputs === null ? 'no_network' : synthetic ? 'synthetic_complete' : 'incomplete',
    coverage_readiness: loaded.manifest.coverage.readiness,
    policy_readiness: loaded.manifest.diagnostics.blockers.length ? 'blocked' : 'ready',
    blockers: loaded.manifest.diagnostics.blockers,
    error_code: outputs === null ? 'no_network' : null,
    outputs,
  };
  validateSchema('result', result);
  return result;
}
