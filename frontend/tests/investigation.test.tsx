import { act,cleanup,fireEvent,render,screen,waitFor } from '@testing-library/react';
import { afterEach,expect,it,vi } from 'vitest';
import { InvestigationPage } from '../src/features/investigation/InvestigationPage';
import { request } from '../src/api/client';
import { deferred } from './helpers';
vi.mock('../src/api/client',()=>({request:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const status={generation:'configured',embedding:'configured',budget:{call_count:0,remaining_calls:20,estimated_spent:null,currency:'USD'}};
it('requires an explicit advisory run before a paid investigation',async()=>{
  vi.mocked(request).mockResolvedValue(status);
  render(<InvestigationPage projectId="p" snapshotId="s" runId="" />);
  expect(screen.getByRole('button',{name:'Ask with evidence'})).toBeDisabled();
  expect(screen.getByText(/Select an advisory query run/i)).toBeInTheDocument();
});
it('withholds a stale answer after switching snapshots',async()=>{
  const pending=deferred<any>();
  vi.mocked(request).mockImplementation((url)=>url==='/api/ai/status'?Promise.resolve(status):url==='/api/investigations'?pending.promise:Promise.resolve({status:'ready',result_id:'old-answer'}));
  const view=render(<InvestigationPage projectId="p" snapshotId="old" runId="run-old" />);
  fireEvent.change(screen.getByLabelText('Investigation question'),{target:{value:'question'}});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Ask with evidence'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Ask with evidence'}));
  await waitFor(()=>expect(request).toHaveBeenCalledWith('/api/investigations',expect.anything()));
  view.rerender(<InvestigationPage projectId="p" snapshotId="new" runId="run-new" />);
  await act(async()=>pending.resolve({job_id:'old-job'}));
  expect(screen.queryByText('old-answer')).not.toBeInTheDocument();
});
