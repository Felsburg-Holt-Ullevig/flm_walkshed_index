import { describe, expect, it } from 'vitest';
import { type Graph, reachable } from './reachability';

const graph: Graph = {
  nodes: ['1', '2', '3'],
  segments: [
    { id: 'AB', lengthFt: 100, seconds: 24.384 },
    { id: 'BC', lengthFt: 100, seconds: 24.384 },
  ],
  arcs: [
    { segment: 'AB', from: '1', to: '2', reverse: false },
    { segment: 'AB', from: '2', to: '1', reverse: true },
    { segment: 'BC', from: '2', to: '3', reverse: false },
  ],
};
describe('literal source-node reachability', () => {
  it('reaches 150 unique feet without counting reverse arcs twice', () => {
    const result = reachable(graph, '1', 36.576);
    expect(result?.unique_source_length_ft).toBeCloseTo(150, 10);
    expect(result?.reached_nodes).toEqual([
      { node_id: '1', seconds: 0 },
      { node_id: '2', seconds: 24.384 },
    ]);
    expect(result?.intervals[1]?.end_ft).toBeCloseTo(50, 10);
  });
  it('does not reverse the one-way segment', () =>
    expect(reachable(graph, '3', 36.576)?.unique_source_length_ft).toBe(0));
  it('preserves zero and missing-origin distinctions', () => {
    expect(reachable(graph, '1', 0)?.reached_nodes).toEqual([{ node_id: '1', seconds: 0 }]);
    expect(reachable(graph, '999', 36.576)).toBeNull();
  });
  it('rejects invalid budgets', () => expect(() => reachable(graph, '1', NaN)).toThrow());
});
