import type { Completeness } from '../api/types';
export function CompletenessBadge({ value }: { value: Completeness }) {
  return <span className={`badge ${value.state === 'complete' ? 'good' : 'amber'}`} title={`${value.unknown_dependencies} dependency declarations unknown`}>{value.state === 'complete' ? 'Structure complete' : value.state === 'partial' ? 'Observed scope only' : 'Structure unknown'}</span>;
}
