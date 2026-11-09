import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import { type Graph, reachable } from '../domain/reachability';

interface Case {
  id: string;
  edges: { id: string; from: string; to: string; length_ft: number; direction: string }[];
  origin: { node: string };
  budget_distance_equivalent_ft: number;
  expected_node_distances_ft: Record<string, number>;
  expected_intervals_ft: Record<string, [number, number][]>;
  expected_unique_source_length_ft: number;
}
const cases = (
  JSON.parse(readFileSync('pipeline/fixtures/routing-references-v1.json', 'utf8')).cases as Case[]
).slice(0, 4);
for (const reference of cases)
  it(`matches accepted Python reference ${reference.id}`, () => {
    const graph: Graph = {
      nodes: [...new Set(reference.edges.flatMap((edge) => [edge.from, edge.to]))],
      segments: reference.edges.map((edge) => ({
        id: edge.id,
        lengthFt: edge.length_ft,
        seconds: edge.length_ft * 0.24384,
      })),
      arcs: reference.edges.flatMap((edge) => [
        { segment: edge.id, from: edge.from, to: edge.to, reverse: false },
        { segment: edge.id, from: edge.to, to: edge.from, reverse: true },
      ]),
    };
    const result = reachable(
      graph,
      reference.origin.node,
      reference.budget_distance_equivalent_ft * 0.24384,
    );
    expect(result?.unique_source_length_ft).toBeCloseTo(
      reference.expected_unique_source_length_ft,
      9,
    );
    expect(result?.reached_nodes.map((node) => node.node_id).sort()).toEqual(
      Object.keys(reference.expected_node_distances_ft).sort(),
    );
    for (const node of result?.reached_nodes ?? [])
      expect(node.seconds).toBeCloseTo(
        (reference.expected_node_distances_ft[node.node_id] ?? NaN) * 0.24384,
        9,
      );
    const expected = Object.entries(reference.expected_intervals_ft).flatMap(
      ([candidate_id, ranges]) =>
        ranges.map(([start_ft, end_ft]) => ({ candidate_id, start_ft, end_ft })),
    );
    expect(result?.intervals).toHaveLength(expected.length);
    for (const range of expected) {
      const actual = result?.intervals.find(
        (interval) =>
          interval.candidate_id === range.candidate_id &&
          Math.abs(interval.start_ft - range.start_ft) < 1e-9,
      );
      expect(actual?.end_ft).toBeCloseTo(range.end_ft, 9);
    }
  });
