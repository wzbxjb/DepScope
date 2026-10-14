import { useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import type { GraphView } from '../../api/types';
export function useSnapshot(snapshotId: string, runId?: string, projectId?: string, revision = 0) {
  const [data, setData] = useState<GraphView>(); const [error, setError] = useState<Error>(); const [loading, setLoading] = useState(true);
  const sequence = useRef(0);
  useEffect(() => {
    const number = ++sequence.current; const controller = new AbortController();
    setData(undefined); setError(undefined); setLoading(true);
    api.graph(snapshotId, controller.signal, runId, projectId).then(value => {
      if (!controller.signal.aborted && sequence.current === number) {
        if (value.snapshot_id !== snapshotId || (runId && value.run_id !== runId)) setError(new Error('Response scope differs from the selected snapshot or query run'));
        else setData(value);
      }
    }).catch((reason: Error) => { if (!controller.signal.aborted && sequence.current === number) setError(reason); })
      .finally(() => { if (!controller.signal.aborted && sequence.current === number) setLoading(false); });
    return () => controller.abort();
  }, [snapshotId, runId, projectId, revision]);
  return { data, error, loading };
}
