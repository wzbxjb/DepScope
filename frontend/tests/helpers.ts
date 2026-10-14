import type { GraphView } from '../src/api/types';
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}
export function graphResponse(snapshotId: string, names: string[]): GraphView {
  return { snapshot_id: snapshotId, run_id: null, observed_at: '2026-10-13T00:00:00Z', query_observed_at: null,
    nodes: names.map((label, i) => ({ id: `${snapshotId}-${i}`, local_id: String(i), label, coordinate: null, query_status: 'unqueried', pointer: `/nodes/${i}` })),
    edges: [], total_nodes: names.length, hidden_nodes: 0,
    completeness: { state: 'complete', root_known: true, unknown_dependencies: 0, issues: [] } };
}
