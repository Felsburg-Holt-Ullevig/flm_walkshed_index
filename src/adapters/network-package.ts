import Ajv2020 from 'ajv/dist/2020';
import GeographicLib from 'geographiclib-geodesic';
import type { Graph } from '../domain/reachability';
import type { HttpsSchemasFlmExampleNetworkPackageV1ArcsSchemaJson as Arcs } from './generated/arcs';
import type { HttpsSchemasFlmExampleNetworkPackageV1InventorySchemaJson as Inventory } from './generated/inventory';
import type { HttpsSchemasFlmExampleNetworkPackageV1ManifestSchemaJson as Manifest } from './generated/manifest';
import type { HttpsSchemasFlmExampleNetworkPackageV1NodesSchemaJson as Nodes } from './generated/nodes';
import type { HttpsSchemasFlmExampleNetworkPackageV1SegmentsSchemaJson as Segments } from './generated/segments';

const schemas = import.meta.glob('../../contracts/network-package/v1/*.schema.json', {
  eager: true,
  import: 'default',
});
const ajv = new Ajv2020({ strict: true, allErrors: true });
for (const schema of Object.values(schemas)) ajv.addSchema(schema as object);
const schemaRoot = 'https://schemas.flm.example/network-package/v1/';
export function validateSchema(name: string, data: unknown) {
  const validate = ajv.getSchema(`${schemaRoot}${name}.schema.json`);
  if (!validate?.(data))
    throw Error(`invalid_content: ${name}: ${ajv.errorsText(validate?.errors)}`);
}

// A token walk preserves duplicate-key detection before JSON.parse discards evidence.
export function strictJson(text: string): unknown {
  try {
    return parseJsonTokens(text);
  } catch (error) {
    if (error instanceof SyntaxError) throw Error('invalid_content: malformed JSON');
    throw error;
  }
}
function parseJsonTokens(text: string): unknown {
  const tokens =
    text.match(/"(?:\\.|[^"\\])*"|[{}[\]:,]|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null/g) ??
    [];
  let index = 0;
  function value(depth: number): void {
    if (depth > 32) throw Error('resource_limit: JSON nesting');
    const token = tokens[index++];
    if (token === '{') {
      const keys = new Set<string>();
      while (tokens[index] !== '}') {
        const key = JSON.parse(tokens[index++] ?? '') as string;
        if (keys.has(key)) throw Error('invalid_content: duplicate key');
        keys.add(key);
        if (tokens[index++] !== ':') throw Error('invalid_content');
        value(depth + 1);
        if (tokens[index] !== ',') break;
        index++;
      }
      if (tokens[index++] !== '}') throw Error('invalid_content');
    } else if (token === '[') {
      while (tokens[index] !== ']') {
        value(depth + 1);
        if (tokens[index] !== ',') break;
        index++;
      }
      if (tokens[index++] !== ']') throw Error('invalid_content');
    } else if (token && /^-?\d/.test(token)) {
      const number = Number(token);
      if (!Number.isFinite(number) || (Number.isInteger(number) && !Number.isSafeInteger(number)))
        throw Error('invalid_content: unsafe number');
    } else if (!token || !/^("|true$|false$|null$)/.test(token)) throw Error('invalid_content');
  }
  value(0);
  if (index !== tokens.length || text.charCodeAt(0) === 0xfeff) throw Error('invalid_content');
  return JSON.parse(text);
}

export async function sha256(bytes: Uint8Array) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new Uint8Array(bytes)))]
    .map((v) => v.toString(16).padStart(2, '0'))
    .join('');
}
export function semanticEncode(value: unknown): unknown {
  if (value === null) return ['null'];
  if (typeof value === 'boolean') return ['bool', value];
  if (typeof value === 'string') {
    if ([...value].some((character) => character.charCodeAt(0) > 127))
      throw Error('invalid_content: non-ASCII identity');
    return ['string', value];
  }
  if (typeof value === 'number') {
    const bytes = new DataView(new ArrayBuffer(8));
    bytes.setFloat64(0, value === 0 ? 0 : value, false);
    return [
      'number',
      [...new Uint8Array(bytes.buffer)].map((b) => b.toString(16).padStart(2, '0')).join(''),
    ];
  }
  if (Array.isArray(value)) return ['array', value.map(semanticEncode)];
  if (typeof value === 'object')
    return [
      'object',
      Object.entries(value as object)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([key, item]) => [key, semanticEncode(item)]),
    ];
  throw Error('invalid_content');
}
const encoder = new TextEncoder();
const close = (a: number, b: number) => Math.abs(a - b) <= Math.max(1e-9, Math.abs(b) * 1e-12);

export interface LoadedPackage {
  manifest: Manifest;
  manifestHash: string;
  graph: Graph;
  loadedBytes: number;
  loadMs: number;
}
export async function loadPackage(
  manifestUrl: string,
  signal?: AbortSignal,
): Promise<LoadedPackage> {
  const url = new URL(manifestUrl, location.href);
  const directory = new URL('.', url).href;
  if (!['http:', 'https:'].includes(url.protocol) || url.search || url.hash)
    throw Error('invalid_content: manifest URL');
  const started = performance.now();
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = setTimeout(abort, 120000);
  let total = 0;
  async function read(target: URL, cap: number) {
    const response = await fetch(target, { signal: controller.signal, redirect: 'error' });
    if (!response.ok || !response.body) throw Error('fetch_failed');
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) break;
        size += chunk.value.length;
        total += chunk.value.length;
        if (size > cap || total > 512 * 1024 ** 2) throw Error('resource_limit: bytes');
        chunks.push(chunk.value);
      }
    } finally {
      await reader.cancel();
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.length;
    }
    return bytes;
  }
  try {
    const manifestBytes = await read(url, 1024 ** 2);
    const manifestValue = strictJson(
      new TextDecoder('utf-8', { fatal: true }).decode(manifestBytes),
    );
    const version = manifestValue as Partial<Manifest>;
    if (
      version.schema_version !== 'flm-package-1' ||
      version.identity?.graph_format !== 'flm-directed-graph-1' ||
      !version.compatible_app_versions?.includes('0.1.0')
    )
      throw Error('unsupported_version');
    validateSchema('manifest', manifestValue);
    const manifest = manifestValue as Manifest;
    const names = Object.values(manifest.files).map((file) => file.path);
    if (new Set(names).size !== names.length || names.includes('manifest.json'))
      throw Error('invalid_content: filenames');
    if (
      manifest.counts.nodes > 600000 ||
      manifest.counts.segments > 700000 ||
      manifest.counts.arcs > 1400000
    )
      throw Error('resource_limit: records');
    const payloads: Record<string, unknown> = {};
    for (const name of ['nodes', 'segments', 'arcs', 'inventory'] as const) {
      const file = manifest.files[name];
      if (file.bytes > 256 * 1024 ** 2) throw Error('resource_limit: declared bytes');
      const target = new URL(file.path, directory);
      if (new URL('.', target).href !== directory) throw Error('invalid_content: path');
      const bytes = await read(target, 256 * 1024 ** 2);
      if (bytes.length !== file.bytes || (await sha256(bytes)) !== file.sha256)
        throw Error('integrity_mismatch');
      const value = strictJson(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
      if ((value as { schema_version?: string }).schema_version !== `flm-${name}-1`)
        throw Error('unsupported_version');
      validateSchema(name, value);
      payloads[name] = value;
    }
    const blockers = manifest.diagnostics.blockers;
    for (const list of [blockers, manifest.coverage.limitations]) {
      if (JSON.stringify(list) !== JSON.stringify([...new Set(list)].sort()))
        throw Error('invalid_content: diagnostic order');
    }
    if (
      manifest.coverage.readiness === 'synthetic_closed' &&
      (blockers.length ||
        manifest.diagnostics.unknown_candidates ||
        manifest.diagnostics.unsupported_restrictions ||
        manifest.diagnostics.unresolved_relation_members)
    )
      throw Error('invalid_content: synthetic readiness');
    for (const bbox of [manifest.coverage.core_bbox, manifest.coverage.extract_bbox]) {
      if (bbox[0] < -180 || bbox[2] > 180 || bbox[1] < -90 || bbox[3] > 90)
        throw Error('invalid_content: geographic bounds');
    }
    const nodes = payloads.nodes as Nodes;
    const inventory = payloads.inventory as Inventory;
    const synthetic = inventory.sources.every((source) => source.kind === 'synthetic');
    if (
      new Set(inventory.sources.map((source) => source.source_id)).size !==
        inventory.sources.length ||
      inventory.sources.length !== manifest.files.inventory.records
    )
      throw Error('invalid_content: inventory membership');
    const core = manifest.coverage.core_bbox,
      extract = manifest.coverage.extract_bbox;
    if (
      !(
        core[0] < core[2] &&
        core[1] < core[3] &&
        extract[0] <= core[0] &&
        extract[1] <= core[1] &&
        extract[2] >= core[2] &&
        extract[3] >= core[3]
      )
    )
      throw Error('invalid_content: bounds');
    if (
      manifest.identity.length_model === 'synthetic_declared_ft' &&
      (!synthetic ||
        manifest.coverage.readiness !== 'synthetic_closed' ||
        !manifest.identity.rule_version.startsWith('synthetic') ||
        !manifest.identity.scenario_id.startsWith('synthetic'))
    )
      throw Error('invalid_content: synthetic profile');
    if (
      !synthetic &&
      (manifest.coverage.readiness !== 'not_established' || !manifest.coverage.limitations.length)
    )
      throw Error('invalid_content: coverage');
    if (
      [manifest.diagnostics.unknown_candidates, manifest.diagnostics.unsupported_restrictions].some(
        (count) => count > 0,
      ) &&
      !manifest.diagnostics.blockers.length
    )
      throw Error('invalid_content: blockers');
    if (
      manifest.diagnostics.unresolved_relation_members > 0 &&
      !manifest.coverage.limitations.length
    )
      throw Error('invalid_content: unresolved coverage');
    if (
      inventory.sources.reduce((sum, source) => sum + source.unknown_records, 0) !==
      manifest.diagnostics.unknown_candidates
    )
      throw Error('invalid_content: unknown counts');
    const segments = payloads.segments as Segments;
    const arcs = payloads.arcs as Arcs;
    for (const payload of [nodes, segments, arcs])
      if (payload.release_id !== manifest.release_id || payload.graph_id !== manifest.graph_id)
        throw Error('release_mismatch');
    if (manifest.identity.source_inventory_sha256 !== manifest.files.inventory.sha256)
      throw Error('integrity_mismatch: inventory');
    const nodeMap = new Map(nodes.nodes.map((n) => [n.node_id, n]));
    const segmentMap = new Map(segments.segments.map((s) => [s.candidate_id, s]));
    const arcMap = new Map(arcs.arcs.map((a) => [a.edge_id, a]));
    if (
      nodeMap.size !== nodes.nodes.length ||
      segmentMap.size !== segments.segments.length ||
      arcMap.size !== arcs.arcs.length
    )
      throw Error('invalid_graph: duplicate IDs');
    for (const [name, array] of [
      ['nodes', nodes.nodes],
      ['segments', segments.segments],
      ['arcs', arcs.arcs],
    ] as const)
      if (array.length !== manifest.counts[name] || array.length !== manifest.files[name].records)
        throw Error('release_mismatch: counts');
    const used = new Set<string>();
    let expectedArcs = 0;
    for (const segment of segments.segments) {
      if (
        segment.candidate_id !== `way/${segment.way_id}/segment/${segment.sequence}` ||
        segment.from_node_id === segment.to_node_id
      )
        throw Error('invalid_graph: candidate');
      const from = nodeMap.get(segment.from_node_id),
        to = nodeMap.get(segment.to_node_id);
      if (
        !from ||
        !to ||
        JSON.stringify(segment.coordinates) !== JSON.stringify([from.coordinate, to.coordinate])
      )
        throw Error('invalid_graph: geometry');
      used.add(from.node_id);
      used.add(to.node_id);
      if (!close(segment.base_seconds, segment.length_ft * 0.24384))
        throw Error('invalid_graph: cost');
      if (manifest.identity.length_model === 'wgs84_geodesic_international_ft') {
        const distance = GeographicLib.Geodesic.WGS84.Inverse(
          from.coordinate[1] ?? NaN,
          from.coordinate[0] ?? NaN,
          to.coordinate[1] ?? NaN,
          to.coordinate[0] ?? NaN,
        ).s12;
        if (distance === undefined || !close(segment.length_ft, distance / 0.3048))
          throw Error('invalid_graph: length');
      }
      for (const direction of segment.direction === 'both'
        ? ['forward', 'reverse']
        : [segment.direction]) {
        expectedArcs++;
        const arc = arcMap.get(`${segment.candidate_id}/${direction}`);
        const reverse = direction === 'reverse';
        if (
          !arc ||
          arc.direction !== direction ||
          arc.candidate_id !== segment.candidate_id ||
          arc.from_node_id !== (reverse ? to.node_id : from.node_id) ||
          arc.to_node_id !== (reverse ? from.node_id : to.node_id)
        )
          throw Error('invalid_graph: directed arc');
      }
    }
    if (expectedArcs !== arcs.arcs.length || used.size !== nodes.nodes.length)
      throw Error('invalid_graph: membership');
    const sortBy = <T>(array: T[], key: (item: T) => string) =>
      [...array].sort((a, b) => (key(a) < key(b) ? -1 : key(a) > key(b) ? 1 : 0));
    const projection = {
      semantic_version: 'flm-graph-semantic-1',
      identity: manifest.identity,
      coverage: manifest.coverage,
      diagnostics: manifest.diagnostics,
      nodes: sortBy(nodes.nodes, (n) => n.node_id),
      segments: sortBy(segments.segments, (s) => s.candidate_id),
      arcs: sortBy(arcs.arcs, (a) => a.edge_id),
    };
    if (
      (await sha256(encoder.encode(JSON.stringify(semanticEncode(projection))))) !==
      manifest.graph_id
    )
      throw Error('release_mismatch: semantic identity');
    if (controller.signal.aborted || performance.now() - started > 120000)
      throw Error(signal?.aborted ? 'cancelled' : 'resource_limit: deadline');
    return {
      manifest,
      manifestHash: await sha256(manifestBytes),
      loadedBytes: total,
      loadMs: performance.now() - started,
      graph: {
        nodes: nodes.nodes.map((n) => n.node_id),
        segments: segments.segments.map((s) => ({
          id: s.candidate_id,
          lengthFt: s.length_ft,
          seconds: s.base_seconds,
        })),
        arcs: arcs.arcs.map((a) => ({
          segment: a.candidate_id,
          from: a.from_node_id,
          to: a.to_node_id,
          reverse: a.direction === 'reverse',
        })),
      },
    };
  } catch (error) {
    if (controller.signal.aborted)
      throw Error(signal?.aborted ? 'cancelled' : 'resource_limit: deadline');
    throw error;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}
