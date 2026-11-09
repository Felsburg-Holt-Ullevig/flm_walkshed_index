import { reachable } from '../domain/reachability';

self.onmessage = (event) => {
  try {
    self.postMessage({ result: reachable(event.data.graph, event.data.origin, event.data.budget) });
  } catch (error) {
    self.postMessage({ error: String(error) });
  }
};
