import { useCallback, useMemo, useState } from 'react';
import { Search, Network, Info } from 'lucide-react';
import { useSnapshot } from './useSnapshot';
import { CompletenessBadge } from '../../components/CompletenessBadge';
import { DependencyGraph } from '../../components/DependencyGraph';
const statusLabel: Record<string, string> = { matched: 'Records returned', no_match: 'No known match', unqueried: 'Unqueried', partial: 'Partially checked', error: 'Source error', conflict: 'Source conflict' };
export function GraphPage({ snapshotId, runId, projectId, revision = 0 }: { snapshotId: string; runId?: string; projectId?: string; revision?: number }) {
  const { data, loading, error } = useSnapshot(snapshotId, runId, projectId, revision);
  const [search, setSearch] = useState(''); const [selectedId, setSelectedId] = useState<string>();
  const select = useCallback((id: string) => setSelectedId(id), []);
  const filtered = useMemo(() => data?.nodes.filter(node => node.label.toLowerCase().includes(search.toLowerCase())) ?? [], [data, search]);
  if (error) return <div role="alert" className="empty-state">Unable to load this snapshot: {error.message}</div>;
  if (loading || !data || data.snapshot_id !== snapshotId) return <div className="loading-state">Loading the selected dependency graph…</div>;
  const selected = data.nodes.find(node => node.id === selectedId);
  return <section data-testid="graph-scope" data-snapshot-id={data.snapshot_id} className="graph-section">
    <div className="section-heading"><div><span className="eyebrow">DEPENDENCY EXPLORER</span><h2>Follow the dependency chain</h2></div><CompletenessBadge value={data.completeness} /></div>
    {data.hidden_nodes > 0 && <div className="notice"><Info size={16} /> {data.hidden_nodes} nodes hidden. Totals use all {data.total_nodes} recorded components.</div>}
    {!data.completeness.root_known && <div className="notice">No project root was provided. Dependency paths remain unknown.</div>}
    {data.nodes.length === 0 ? <div className="empty-state"><Network size={36} /><p>No recorded dependencies in this snapshot.</p></div> : <>
      <div className="graph-surface"><div className="graph-legend"><span><i className="dot teal" /> Recorded dependency</span><span><i className="dot coral" /> Advisory records returned</span><span><i className="dot amber-dot" /> Query unknown</span></div><DependencyGraph graph={data} onSelect={select} /><div className="graph-caption">Scroll to zoom · drag to explore · select a node for its source</div></div>
      {selected && <div className="selected-package"><strong>{selected.label}</strong><span>{statusLabel[selected.query_status] ?? selected.query_status}</span><code>{selected.pointer}</code><button className="text-button" onClick={() => setSelectedId(undefined)}>Close</button></div>}
      <div className="table-toolbar"><h3>Recorded packages <span className="count-pill">{data.total_nodes}</span></h3><label className="search-field"><Search size={16} /><input aria-label="Search recorded packages" placeholder="Find a package…" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
      <div className="table-wrap"><table><thead><tr><th>Package</th><th>Version</th><th>Query status</th><th>Evidence location</th></tr></thead><tbody>{filtered.map(node => <tr key={node.id}><td><button className="package-button" onClick={() => select(node.id)}>{node.coordinate?.name ?? node.label}</button></td><td><code>{node.coordinate?.raw_version ?? 'Unknown'}</code></td><td><span className={`status-label ${node.query_status === 'matched' ? 'coral-text' : ''}`}>{statusLabel[node.query_status] ?? node.query_status}</span></td><td><code>{node.pointer}</code></td></tr>)}</tbody></table></div>
    </>}
  </section>;
}
