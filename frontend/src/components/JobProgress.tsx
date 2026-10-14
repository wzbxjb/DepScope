import { useEffect, useState } from 'react';
import { LoaderCircle, Check, X } from 'lucide-react';
import { api } from '../api/client';
import type { Job } from '../api/types';
const final = new Set(['ready', 'failed', 'cancelled', 'interrupted']);
export function JobProgress({ id, onDone }: { id: string; onDone: (job: Job) => void }) {
  const [job, setJob] = useState<Job>(); const [error, setError] = useState('');
  useEffect(() => {
    let active = true; let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const value = await api.job(id); if (!active) return; setJob(value);
        if (final.has(value.status)) onDone(value); else timer = setTimeout(poll, 700);
      } catch (reason) { if (active) setError((reason as Error).message); }
    };
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [id, onDone]);
  return <div className="job-toast" role="status"><span className="job-icon">{job?.status === 'ready' ? <Check size={18} /> : <LoaderCircle size={18} className="spin" />}</span><div><strong>{job?.status === 'ready' ? 'Results ready' : job?.status === 'failed' ? 'Task failed' : job?.status === 'cancelled' ? 'Task cancelled' : 'Preparing evidence'}</strong><span>{error || job?.error?.message || (job?.cancel_requested ? 'Cancellation requested' : job?.phase ?? 'Waiting in queue')}</span><div className="progress-track"><i style={{ width: `${Math.max(3, (job?.progress ?? 0) * 100)}%` }} /></div></div>{job && !final.has(job.status) && <button className="icon-button" aria-label="Cancel task" onClick={() => void api.cancelJob(id)}><X size={16} /></button>}</div>;
}
