import type { Comparison, Finding, GraphView, Job, MatchRun, Page, PathResult, Project, RunSummary, Snapshot, SnapshotSummary } from './types';
export class ApiError extends Error {
  constructor(message: string, public code: string, public pointers: string[] = []) { super(message); }
}
export async function request<T>(url: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(data?.error?.message ?? `Service request failed (${response.status})`, data?.error?.code ?? 'HTTP_ERROR', data?.error?.pointers ?? []);
  return data as T;
}
export async function fetchPage<T>(url: string, signal?: AbortSignal): Promise<Page<T>> {
  return request<Page<T>>(url, { signal });
}
export async function fetchAll<T>(url: string, signal?: AbortSignal): Promise<T[]> {
  const items: T[] = []; const seen = new Set<string>(); let cursor: string | null = null;
  do {
    const target = new URL(url, window.location.origin);
    target.searchParams.set('limit', '100');
    if (cursor) target.searchParams.set('cursor', cursor);
    const page = await fetchPage<T>(target.pathname + target.search, signal);
    items.push(...page.items); cursor = page.next_cursor;
    if (cursor && seen.has(cursor)) throw new ApiError('Pagination returned a repeated cursor', 'INVALID_PAGINATION');
    if (cursor) seen.add(cursor);
  } while (cursor);
  return items;
}
const post = <T,>(url: string, body?: unknown) => request<T>(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });
export const api = {
  projects: (signal?: AbortSignal) => fetchAll<Project>('/api/projects', signal),
  createProject: (name: string) => post<{ id: string }>('/api/projects', { name }),
  snapshots: (id: string, signal?: AbortSignal) => fetchAll<SnapshotSummary>(`/api/projects/${id}/snapshots`, signal),
  snapshot: (id: string, signal?: AbortSignal) => request<Snapshot>(`/api/snapshots/${id}`, { signal }),
  runs: (id: string, signal?: AbortSignal) => fetchAll<RunSummary>(`/api/snapshots/${id}/match-runs`, signal),
  run: (id: string, signal?: AbortSignal) => request<MatchRun>(`/api/match-runs/${id}`, { signal }),
  findings: (id: string, signal?: AbortSignal) => fetchAll<Finding>(`/api/match-runs/${id}/findings`, signal),
  graph: (id: string, signal?: AbortSignal, runId?: string, projectId?: string) => {
    const query = new URLSearchParams(); if (runId) query.set('run_id', runId); if (projectId) query.set('project_id', projectId);
    return request<GraphView>(`/api/snapshots/${id}/graph?${query}`, { signal });
  },
  paths: (id: string, mapping: Record<string, string>, signal?: AbortSignal) => request<PathResult>(`/api/findings/${id}/paths?${new URLSearchParams({ run_map: JSON.stringify(mapping) })}`, { signal }),
  advisory: (id: string, signal?: AbortSignal) => request<{ id: string; summary: string; details: string; aliases: string[]; source: { uri: string; digest: string; observed_at: string } }>(`/api/advisory-revisions/${id}`, { signal }),
  upload: (project: string, file: File) => request<{ job_id: string }>(`/api/projects/${project}/imports`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: file }),
  publicResolution: (project: string, name: string, version: string) => post<{ job_id: string }>(`/api/projects/${project}/public-resolutions`, { name, version }),
  loadSample: () => post<{ job_id: string }>('/api/demo/public-sample'),
  match: (id: string) => post<{ job_id: string }>(`/api/snapshots/${id}/match-runs`),
  job: (id: string) => request<Job>(`/api/jobs/${id}`),
  cancelJob: (id: string) => post<Job>(`/api/jobs/${id}/cancel`),
  retryJob: (id: string) => post<{ job_id: string }>(`/api/jobs/${id}/retry`),
  compare: (baseline_id: string, candidate_id: string) => post<{ job_id: string }>('/api/comparisons', { baseline_id, candidate_id }),
  comparison: (id: string) => request<Comparison>(`/api/comparisons/${id}`),
};
