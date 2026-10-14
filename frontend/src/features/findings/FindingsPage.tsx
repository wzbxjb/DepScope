import { useEffect, useState } from 'react';
import { ArrowRight, FileText, Route, ShieldCheck } from 'lucide-react';
import { api } from '../../api/client';
import type { Finding, MatchRun, PathResult } from '../../api/types';
import { EvidenceLink } from '../../components/EvidenceLink';
export function FindingsPage({ run }: { run: MatchRun }) {
  const [findings, setFindings] = useState<Finding[]>([]); const [selected, setSelected] = useState<string>();
  const [paths, setPaths] = useState<PathResult>(); const [source, setSource] = useState<Awaited<ReturnType<typeof api.advisory>>>(); const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setFindings([]); setSelected(undefined); setPaths(undefined); setSource(undefined); setError('');
    api.findings(run.id, controller.signal).then(values => { if (!controller.signal.aborted) setFindings(values); }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [run.id]);
  useEffect(() => {
    if (!selected) return; const finding = findings.find(value => value.id === selected); if (!finding) return;
    const controller = new AbortController(); setPaths(undefined); setSource(undefined);
    Promise.all([api.paths(selected, { [run.snapshot_id]: run.id }, controller.signal), api.advisory(finding.revision_ids[0], controller.signal)]).then(([path, advisory]) => { if (!controller.signal.aborted) { setPaths(path); setSource(advisory); } }).catch(reason => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [selected, findings, run]);
  return <section><div className="section-heading"><div><span className="eyebrow">ADVISORY EVIDENCE</span><h2>Known matches, with a trace</h2></div><span className="badge neutral">{new Date(run.observed_at).toLocaleString()}</span></div>
    <div className="notice">{run.coverage.confirmed} / {run.coverage.total} reliable package versions fully queried · {run.coverage.unknown} unknown · {run.coverage.opaque_instances ?? 0} components without reliable coordinates</div>
    {error && <p role="alert" className="error-text">{error}</p>}
    {findings.length === 0 ? <div className="empty-state"><ShieldCheck size={36} /><h3>No active matches recorded</h3><p>Query coverage and unknown components still apply.</p></div> : <div className="evidence-layout"><div className="finding-list">{findings.map((finding, index) => <button className={`finding-card ${selected === finding.id ? 'selected' : ''}`} key={finding.id} onClick={() => setSelected(finding.id)}><span className="finding-number">{String(index + 1).padStart(2, '0')}</span><span><strong>{finding.package_name ?? finding.component_name ?? 'Advisory match'}{finding.raw_version ? '@' + finding.raw_version : ''}</strong><small>{finding.advisory_ids?.[0] ?? 'Advisory match'} · {finding.revision_ids.length} supporting record{finding.revision_ids.length > 1 ? 's' : ''} · alias duplicates merged</small></span><ArrowRight size={16} /></button>)}</div><div className="evidence-detail">{!selected ? <div className="empty-state"><FileText size={32} /><p>Select a match to inspect its source and dependency path.</p></div> : !source || !paths ? <div className="loading-state">Tracing recorded evidence…</div> : <>
      <div className="source-heading"><span className="badge amber">{source.id}</span><h3>{source.summary || source.id}</h3><EvidenceLink uri={source.source.uri} digest={source.source.digest} /></div>
      <h4><Route size={16} /> Recorded impact paths</h4>{paths.paths.map(path => <div className="dependency-path" key={path.finding_id}>{path.labels.map((name, index) => <span key={`${index}-${name}`}>{index > 0 && <ArrowRight size={13} />}<code>{name}</code></span>)}</div>)}
      {paths.paths.length === 0 && <p className="muted">No root path can be confirmed in the selected source.</p>}
      <p className="small muted">{paths.reachable_matches} reachable matches · {paths.unreachable_matches} disconnected · {paths.unknown_paths} unknown paths. Each path stays inside its snapshot.</p>
      <details><summary>Read advisory details</summary><div className="source-text">{source.details}</div></details><p className="small muted">A recorded match does not establish runtime exploitability.</p>
    </>}</div></div>}
  </section>;
}
