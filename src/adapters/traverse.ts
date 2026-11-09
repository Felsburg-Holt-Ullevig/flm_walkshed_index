import type { Graph, reachable } from '../domain/reachability';
export function traverse(
  graph: Graph,
  origin: string,
  budget: number,
  signal: AbortSignal,
): Promise<ReturnType<typeof reachable>> {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('../workers/reachability.ts', import.meta.url), {
      type: 'module',
    });
    const cleanup = () => {
      clearTimeout(timer);
      worker.terminate();
      signal.removeEventListener('abort', abort);
    };
    const abort = () => {
      cleanup();
      reject(Error('cancelled'));
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(Error('resource_limit: traversal deadline'));
    }, 120000);
    signal.addEventListener('abort', abort, { once: true });
    worker.onmessage = (event) => {
      cleanup();
      if (event.data.error) reject(Error(event.data.error));
      else resolve(event.data.result);
    };
    worker.onerror = () => {
      cleanup();
      reject(Error('traversal_failed'));
    };
    if (signal.aborted) abort();
    else worker.postMessage({ graph, origin, budget });
  });
}
