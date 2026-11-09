import { useRef, useState } from 'react';
import { type LoadedPackage, loadPackage } from '../adapters/network-package';
import { bindResult } from '../adapters/reachable-result';
import { traverse } from '../adapters/traverse';
import type { reachable } from '../domain/reachability';

export function App() {
  const job = useRef<AbortController | null>(null);
  const [url, setUrl] = useState('./__network-fixture__/manifest.json');
  const [active, setActive] = useState<LoadedPackage | null>(null);
  const [status, setStatus] = useState('No package loaded');
  const [busy, setBusy] = useState(false);
  const [origin, setOrigin] = useState('1');
  const [budget, setBudget] = useState('36.576');
  const [result, setResult] = useState<ReturnType<typeof reachable> | undefined>();
  async function load() {
    setBusy(true);
    job.current = new AbortController();
    try {
      const candidate = await loadPackage(url, job.current.signal);
      setActive(candidate);
      setResult(undefined);
      setStatus(
        `Loaded ${candidate.manifest.release_id}; ${candidate.loadedBytes} bytes; ${candidate.loadMs.toFixed(1)} ms`,
      );
    } catch (error) {
      setStatus(String(error));
    } finally {
      setBusy(false);
    }
  }
  async function compute() {
    if (!active) return;
    if (!/^[1-9][0-9]*$/.test(origin) || budget.trim() === '') {
      setStatus('invalid_request: source node and budget required');
      return;
    }
    setBusy(true);
    job.current = new AbortController();
    const started = performance.now();
    try {
      const output = await traverse(active.graph, origin, Number(budget), job.current.signal);
      setResult(output);
      setStatus(
        `${output === null ? 'no_network' : active.manifest.coverage.readiness === 'synthetic_closed' ? 'synthetic_complete' : 'incomplete'}; computation ${(performance.now() - started).toFixed(2)} ms`,
      );
    } catch (error) {
      setStatus(String(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <main>
        <h1>Experimental network review</h1>
        <p>
          Source-node pedestrian diagnostic. Coverage and station entrances are unverified. No
          scores or wheelchair accessibility assessment.
        </p>
        <label>
          Package manifest URL
          <input disabled={busy} value={url} onChange={(event) => setUrl(event.target.value)} />
        </label>
        <button type="button" disabled={busy} onClick={load}>
          Load package
        </button>
        {busy && (
          <button type="button" onClick={() => job.current?.abort()}>
            Cancel
          </button>
        )}
        <p role="status">{status}</p>
        {active && (
          <p>
            Active release: {active.manifest.release_id}. Coverage:{' '}
            {active.manifest.coverage.readiness}. Analytical promotion: blocked experimental.
          </p>
        )}
        <label>
          Source node ID
          <input
            disabled={busy}
            value={origin}
            onChange={(event) => {
              setOrigin(event.target.value);
              setResult(undefined);
            }}
          />
        </label>
        <label>
          Walking budget (seconds)
          <input
            disabled={busy}
            type="number"
            min="0"
            max="3600"
            step="any"
            value={budget}
            onChange={(event) => {
              setBudget(event.target.value);
              setResult(undefined);
            }}
          />
        </label>
        <button type="button" disabled={!active || busy} onClick={compute}>
          Calculate reachability
        </button>
        {result === null && <p>No network origin found. Outputs are null.</p>}
        {result && (
          <>
            <h2>Reachable source network</h2>
            <p data-testid="total">
              Unique length: {result.unique_source_length_ft.toFixed(6)} feet
            </p>
            <pre>
              {JSON.stringify(
                active ? bindResult(active, origin, Number(budget), result) : null,
                null,
                2,
              )}
            </pre>
          </>
        )}
      </main>
      <footer>
        <p>Build {__APP_COMMIT__}</p>
      </footer>
    </>
  );
}
