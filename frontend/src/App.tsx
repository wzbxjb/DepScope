import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, ArrowUpRight, ChevronDown, FileJson, GitCompareArrows, Layers, Network, Plus, MessageSquare, ShieldCheck, Upload } from 'lucide-react';
import { api, request } from './api/client';
import type { Comparison, Job, MatchRun, Project, RunSummary, Snapshot, SnapshotSummary } from './api/types';
import { GraphPage } from './features/graph/GraphPage';
import { FindingsPage } from './features/findings/FindingsPage';
import { ComparisonsPage, snapshotLabel } from './features/comparisons/ComparisonsPage';
import { InvestigationPage } from './features/investigation/InvestigationPage';
import { ImportDialog } from './features/projects/ImportDialog';
import { JobProgress } from './components/JobProgress';
import { EvidenceLink } from './components/EvidenceLink';
export default function App() {
  const [projects, setProjects] = useState<Project[]>([]); const [projectId, setProjectId] = useState('');
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]); const [snapshotId, setSnapshotId] = useState('');
  const [snapshot, setSnapshot] = useState<Snapshot>(); const [runs, setRuns] = useState<RunSummary[]>([]); const [runId, setRunId] = useState(''); const [run, setRun] = useState<MatchRun>();
  const [page, setPage] = useState('graph'); const [jobIds, setJobIds] = useState<string[]>([]); const [comparison, setComparison] = useState<Comparison>();
  const [revision, setRevision] = useState(0); const [error, setError] = useState(''); const [showImport, setShowImport] = useState(false); const [creating, setCreating] = useState(false); const [newName, setNewName] = useState('');
  const preferred = useRef<Record<string, string>>({});
  const [health, setHealth] = useState<{ status: string; generation: string }>(); const selection = useRef({ projectId, snapshotId }); selection.current = { projectId, snapshotId };
  const refreshProjects = useCallback(async () => { const values = await api.projects(); setProjects(values); return values; }, []);
  useEffect(() => { void refreshProjects().then(values => { const first = values.find(value => value.kind === 'public_demo') ?? values[0]; if (first) setProjectId(first.id); }).catch(reason => setError(reason.message)); void request<{ status: string; generation: string }>('/health/ready').then(setHealth).catch(() => undefined); }, [refreshProjects]);
  useEffect(() => {
    setSnapshots([]); setSnapshotId(''); setSnapshot(undefined); setRun(undefined); setRunId(''); setComparison(undefined);
    if (!projectId) return; const controller = new AbortController();
    api.snapshots(projectId, controller.signal).then(values => { if (!controller.signal.aborted) { setSnapshots(values); if (values.length) setSnapshotId(values.find(value => value.snapshot_id === preferred.current[projectId])?.snapshot_id ?? values[0].snapshot_id); } }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [projectId]);
  useEffect(() => {
    setSnapshot(undefined); setRuns([]); setRunId(''); setRun(undefined); if (!snapshotId) return;
    const controller = new AbortController();
    Promise.all([api.snapshot(snapshotId, controller.signal), api.runs(snapshotId, controller.signal)]).then(([value, history]) => {
      if (!controller.signal.aborted && value.snapshot_id === snapshotId) { setSnapshot(value); history.sort((a, b) => Date.parse(b.observed_at) - Date.parse(a.observed_at)); setRuns(history); if (history.length) setRunId(history[0].id); }
    }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [snapshotId, revision]);
  useEffect(() => {
    setRun(undefined); if (!runId) return; const controller = new AbortController();
    api.run(runId, controller.signal).then(value => { if (!controller.signal.aborted && value.snapshot_id === snapshotId) setRun(value); }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [runId, snapshotId]);
  const onJob = useCallback((id: string) => setJobIds(values => values.includes(id) ? values : [...values, id]), []);
  const onDone = useCallback((job: Job) => {
    setJobIds(values => values.filter(value => value !== job.id));
    if (job.status !== 'ready') { if (job.error) setError(job.error.message); return; }
    void (async () => {
      await refreshProjects();
      if (job.kind === 'sample' && job.result_id) { const value = await api.snapshot(job.result_id); preferred.current[value.project_id] = value.snapshot_id; setProjectId(value.project_id); const items = await api.snapshots(value.project_id); setSnapshots(items); setSnapshotId(value.snapshot_id); setPage('graph'); }
      else if (job.kind === 'import' && job.result_id) { const value = await api.snapshot(job.result_id); const items = await api.snapshots(value.project_id); if (selection.current.projectId === value.project_id) { preferred.current[value.project_id] = value.snapshot_id; setSnapshots(items); setSnapshotId(value.snapshot_id); } }
      else if (job.kind === 'match') setRevision(value => value + 1);
      else if (job.kind === 'compare' && job.result_id) { const value = await api.comparison(job.result_id); const baseline = await api.snapshot(value.baseline_id); if (selection.current.projectId === baseline.project_id) { setComparison(value); setPage('comparisons'); } }
    })().catch(reason => setError(reason.message));
  }, [refreshProjects]);
  const loadSample = async () => { try { setError(''); onJob((await api.loadSample()).job_id); } catch (reason) { setError((reason as Error).message); } };
  const createProject = async () => { try { const value = await api.createProject(newName); await refreshProjects(); setProjectId(value.id); setCreating(false); setNewName(''); } catch (reason) { setError((reason as Error).message); } };
  const activeProject = projects.find(value => value.id === projectId); const summary = snapshots.find(value => value.snapshot_id === snapshotId);
  const currentSnapshot = snapshot?.snapshot_id === snapshotId ? snapshot : undefined; const currentRun = run?.snapshot_id === snapshotId && run.id === runId ? run : undefined;
  const links = [{ id: 'graph', label: 'Dependency explorer', icon: Network }, { id: 'findings', label: 'Advisory matches', icon: ShieldCheck }, { id: 'comparisons', label: 'Compare snapshots', icon: GitCompareArrows }, { id: 'investigation', label: 'AI investigation', icon: MessageSquare }];
  return <div className="app-shell"><aside className="sidebar"><a className="brand" href="/"><span className="brand-mark"><Network size={25} /></span><span>DepScope<small>DEPENDENCY INTELLIGENCE</small></span></a><div className="workspace-label">YOUR WORKSPACE <span className="workspace-dot" /></div><label className="project-selector"><Layers size={17} /><select aria-label="Project" value={projectId} onChange={event => setProjectId(event.target.value)}><option value="">Choose project</option>{projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}</select><ChevronDown size={14} /></label><button className="new-project" onClick={() => setCreating(true)}><Plus size={15} /> New project</button><nav>{links.map(link => <button className={page === link.id ? 'active' : ''} onClick={() => setPage(link.id)} key={link.id}><link.icon size={18} /><span>{link.label}</span>{link.id === 'findings' && currentRun && <b>{currentRun.coverage.active_findings}</b>}</button>)}</nav><div className="sidebar-note"><FileJson size={20} /><strong>Every answer starts with evidence.</strong><p>Trace recorded dependencies and keep unknowns visible.</p></div><div className="sidebar-status"><span className="status-dot" />{health?.status === 'ready' ? 'Graph service ready' : 'Checking service'}<small>Local workspace · private credentials</small></div></aside>
    <main className="main-content"><header className="topbar"><div className="breadcrumb">Workspace <span>/</span> {activeProject?.name ?? 'Get started'}</div><span className="workspace-badge"><Activity size={14} /> Evidence workspace</span></header><div className="content"><div className="page-title"><div><div className="eyebrow">SOFTWARE SUPPLY CHAIN</div><h1>Understand what your app depends on.</h1><p>Trace indirect dependencies, inspect advisory evidence, and compare upgrade candidates.</p></div><button className="outline-button" onClick={() => void loadSample()}>Load verified public sample <ArrowUpRight size={16} /></button></div>
      {error && <div className="error-banner" role="alert">{error}<button className="text-button" onClick={() => setError('')}>Dismiss</button></div>}
      {projectId && <div className="scope-bar"><label>DEPENDENCY SNAPSHOT<select aria-label="Snapshot" value={snapshotId} onChange={event => setSnapshotId(event.target.value)}><option value="">Choose snapshot</option>{snapshots.map(value => <option key={value.snapshot_id} value={value.snapshot_id}>{snapshotLabel(value)}</option>)}</select></label><label>ADVISORY QUERY<select aria-label="Advisory query run" value={runId} onChange={event => setRunId(event.target.value)}><option value="">Not queried</option>{runs.map(value => <option key={value.id} value={value.id}>{new Date(value.observed_at).toLocaleString()}</option>)}</select></label><button className="outline-button" onClick={() => setShowImport(true)}><Upload size={15} /> Add snapshot</button>{snapshotId && <button className="text-button" onClick={() => void api.match(snapshotId).then(value => onJob(value.job_id)).catch(reason => setError(reason.message))}>Refresh advisories</button>}</div>}
      {snapshotId && summary ? <><div className="metric-grid"><div className="metric-card"><span>Recorded components</span><strong>{summary.component_count}<Network size={21} /></strong><small>Full snapshot inventory</small></div><div className="metric-card"><span>Dependency relations</span><strong>{summary.edge_count}<Layers size={21} /></strong><small>Context stays inside this snapshot</small></div><div className="metric-card accent-card"><span>Active instance matches</span><strong>{currentRun?.coverage.active_findings ?? '—'}<ShieldCheck size={21} /></strong><small>{currentRun ? 'Alias duplicates merged' : 'Advisories not queried'}</small></div><div className="metric-card"><span>Reliable versions queried</span><strong>{currentRun ? `${currentRun.coverage.confirmed}/${currentRun.coverage.total}` : '—'}<Activity size={21} /></strong><small>{currentRun ? `${currentRun.coverage.unknown} unknown · ${currentRun.coverage.opaque_instances ?? 0} opaque components` : 'Coverage unavailable'}</small></div></div>
        <div className="workspace-panel">{page === 'graph' && <GraphPage snapshotId={snapshotId} runId={runId || undefined} projectId={projectId} revision={revision} />}{page === 'findings' && (currentRun ? <FindingsPage run={currentRun} /> : <div className="empty-state">Refresh advisories to inspect a query run.</div>)}{page === 'investigation' && <InvestigationPage projectId={projectId} snapshotId={snapshotId} runId={runId} comparison={comparison} />}{page === 'comparisons' && <ComparisonsPage key={projectId} snapshots={snapshots} onJob={onJob} result={comparison} />}</div>{currentSnapshot && <footer className="source-footer"><span>Snapshot observed {new Date(currentSnapshot.source.observed_at).toLocaleString()} · {currentSnapshot.source_kind.replaceAll('_', ' ')}</span><EvidenceLink uri={currentSnapshot.source.uri} digest={currentSnapshot.source.digest} /></footer>}
      </> : <div className="welcome-panel"><div className="welcome-icon"><Network size={44} /></div><span className="eyebrow">START WITH A REAL INVENTORY</span><h2>Make the dependency chain visible.</h2><p>Load the verified LangChain sample, or create a project and upload an inventory from your own environment.</p><button className="primary-button" onClick={() => void loadSample()}>Load verified public sample <ArrowRightIcon /></button></div>}
      <div className="bottom-note"><i className="dot teal" /> Recorded facts and source receipts · query failures stay unknown</div>
    </div></main>{showImport && <ImportDialog projectId={projectId} onJob={onJob} onClose={() => setShowImport(false)} />}{creating && <div className="modal-backdrop"><form className="modal" onSubmit={event => { event.preventDefault(); void createProject(); }}><h2>Create a project</h2><label>Project name<input autoFocus value={newName} required maxLength={200} onChange={event => setNewName(event.target.value)} placeholder="My AI application" /></label><div className="dialog-actions"><button type="button" className="outline-button" onClick={() => setCreating(false)}>Cancel</button><button className="primary-button">Create project</button></div></form></div>}<div className="job-stack">{jobIds.map(id => <JobProgress id={id} onDone={onDone} key={id} />)}</div></div>;
}
function ArrowRightIcon() { return <ArrowUpRight size={16} />; }
