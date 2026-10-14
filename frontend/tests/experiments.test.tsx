import { render,screen } from '@testing-library/react';
import { afterEach,expect,it,vi } from 'vitest';
import { ExperimentsPage } from '../src/features/experiments/ExperimentsPage';
afterEach(()=>vi.restoreAllMocks());
it('shows an honest empty state when no actual experiment exists',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({items:[],next_cursor:null,observed_at:'2026-10-14T00:00:00Z'})})));
  render(<ExperimentsPage/>);
  expect(await screen.findByText('No recorded experiment yet.')).toBeVisible();
  expect(screen.queryByText('100%')).not.toBeInTheDocument();
});
