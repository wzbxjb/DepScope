import { act, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { GraphPage } from '../src/features/graph/GraphPage';
import { api } from '../src/api/client';
import { deferred, graphResponse } from './helpers';
vi.mock('cytoscape', () => ({ default: vi.fn(() => ({ on: vi.fn(), destroy: vi.fn() })) }));
vi.mock('../src/api/client', () => ({ api: { graph: vi.fn() } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it('ignores a late response from the previous snapshot', async () => {
  const oldRequest = deferred<ReturnType<typeof graphResponse>>();
  vi.mocked(api.graph).mockImplementation((id) => id === 'old' ? oldRequest.promise : Promise.resolve(graphResponse('new', [])));
  const view = render(<GraphPage snapshotId="old" />);
  view.rerender(<GraphPage snapshotId="new" />);
  await waitFor(() => expect(screen.getByTestId('graph-scope')).toHaveAttribute('data-snapshot-id', 'new'));
  await act(async () => oldRequest.resolve(graphResponse('old', ['stale-node'])));
  expect(screen.getByTestId('graph-scope')).toHaveAttribute('data-snapshot-id', 'new');
  expect(screen.queryByText('stale-node')).not.toBeInTheDocument();
});
it('shows full totals when the graph view is collapsed', async () => {
  const response = { ...graphResponse('large', ['root']), total_nodes: 350, hidden_nodes: 349 };
  vi.mocked(api.graph).mockResolvedValue(response);
  render(<GraphPage snapshotId="large" />);
  await waitFor(() => expect(screen.getByText(/349 nodes hidden/)).toBeInTheDocument());
  expect(screen.getByTestId('graph-scope')).toHaveAttribute('data-snapshot-id', 'large');
});
it('rejects a response whose scope differs from the requested snapshot', async () => {
  vi.mocked(api.graph).mockResolvedValue(graphResponse('foreign', ['wrong-node']));
  render(<GraphPage snapshotId="current" />);
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/scope/i));
  expect(screen.queryByText('wrong-node')).not.toBeInTheDocument();
});
