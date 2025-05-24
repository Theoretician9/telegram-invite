import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from 'react-query';
import Invite from '../Invite';
import { startInvite, getInviteStatus } from '../../api/invite';

// Mock the API
jest.mock('../../api/invite');

const mockStatus = {
  task_id: '123',
  status: 'running',
  progress: 5,
  total: 10,
  success: 3,
  failed: 2,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

describe('Invite', () => {
  const queryClient = new QueryClient();

  beforeEach(() => {
    (startInvite as jest.Mock).mockResolvedValue(mockStatus);
    (getInviteStatus as jest.Mock).mockResolvedValue(mockStatus);
  });

  it('renders without crashing', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Invite />
      </QueryClientProvider>
    );

    expect(screen.getByText('Invite Users')).toBeInTheDocument();
    expect(screen.getByLabelText('Target Chat')).toBeInTheDocument();
    expect(screen.getByLabelText('Message')).toBeInTheDocument();
    expect(screen.getByText('Start Invite')).toBeInTheDocument();
  });

  it('handles form submission', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Invite />
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByLabelText('Target Chat'), {
      target: { value: 'test_chat' },
    });
    fireEvent.change(screen.getByLabelText('Message'), {
      target: { value: 'Test message' },
    });
    fireEvent.click(screen.getByText('Start Invite'));

    await waitFor(() => {
      expect(startInvite).toHaveBeenCalledWith({
        target: 'test_chat',
        message: 'Test message',
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Status: running')).toBeInTheDocument();
      expect(screen.getByText('Progress: 5 / 10')).toBeInTheDocument();
      expect(screen.getByText('Success: 3')).toBeInTheDocument();
      expect(screen.getByText('Failed: 2')).toBeInTheDocument();
    });
  });

  it('handles API error', async () => {
    (startInvite as jest.Mock).mockRejectedValue(new Error('API Error'));

    render(
      <QueryClientProvider client={queryClient}>
        <Invite />
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByLabelText('Target Chat'), {
      target: { value: 'test_chat' },
    });
    fireEvent.change(screen.getByLabelText('Message'), {
      target: { value: 'Test message' },
    });
    fireEvent.click(screen.getByText('Start Invite'));

    await waitFor(() => {
      expect(screen.getByText('No active task')).toBeInTheDocument();
    });
  });
}); 