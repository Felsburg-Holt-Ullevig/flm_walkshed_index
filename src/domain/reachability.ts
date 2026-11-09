export interface Graph {
  nodes: readonly string[];
  segments: readonly { id: string; lengthFt: number; seconds: number }[];
  arcs: readonly { segment: string; from: string; to: string; reverse: boolean }[];
}

export function reachable(graph: Graph, origin: string, budget: number) {
  if (!Number.isFinite(budget) || budget < 0 || budget > 3600) throw Error('invalid_request');
  if (!graph.nodes.includes(origin)) return null;
  const segments = new Map(graph.segments.map((s) => [s.id, s]));
  const adjacency = new Map<string, Graph['arcs'][number][]>();
  for (const arc of graph.arcs) {
    const edges = adjacency.get(arc.from) ?? [];
    edges.push(arc);
    adjacency.set(arc.from, edges);
  }
  const costs = new Map([[origin, 0]]);
  const queue: [number, string][] = [[0, origin]];
  while (queue.length) {
    queue.sort((a, b) => b[0] - a[0]);
    const entry = queue.pop();
    if (!entry) break;
    const [cost, node] = entry;
    if (cost !== costs.get(node)) continue;
    for (const arc of adjacency.get(node) ?? []) {
      const segment = segments.get(arc.segment);
      if (!segment) throw Error('invalid_graph');
      const next = cost + segment.seconds;
      if (next <= budget && next < (costs.get(arc.to) ?? Infinity)) {
        costs.set(arc.to, next);
        queue.push([next, arc.to]);
      }
    }
  }
  const ranges = new Map<string, [number, number][]>();
  for (const arc of graph.arcs) {
    const cost = costs.get(arc.from);
    const segment = segments.get(arc.segment);
    if (cost === undefined || !segment) continue;
    const length = Math.min(
      segment.lengthFt,
      ((budget - cost) / segment.seconds) * segment.lengthFt,
    );
    if (length <= 0) continue;
    const intervals = ranges.get(arc.segment) ?? [];
    intervals.push(arc.reverse ? [segment.lengthFt - length, segment.lengthFt] : [0, length]);
    ranges.set(arc.segment, intervals);
  }
  const intervals: { candidate_id: string; start_ft: number; end_ft: number }[] = [];
  for (const [id, rangesForSegment] of [...ranges].sort(([a], [b]) => a.localeCompare(b))) {
    rangesForSegment.sort((a, b) => a[0] - b[0]);
    for (const [start, end] of rangesForSegment) {
      const last = intervals.at(-1);
      if (last?.candidate_id === id && start <= last.end_ft)
        last.end_ft = Math.max(last.end_ft, end);
      else intervals.push({ candidate_id: id, start_ft: start, end_ft: end });
    }
  }
  return {
    reached_nodes: [...costs]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([node_id, seconds]) => ({ node_id, seconds })),
    intervals,
    unique_source_length_ft: intervals.reduce(
      (total, interval) => total + interval.end_ft - interval.start_ft,
      0,
    ),
  };
}
