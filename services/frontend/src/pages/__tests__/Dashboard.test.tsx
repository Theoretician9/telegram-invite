import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from 'react-query';
import Dashboard from '../Dashboard';
import { getStats } from '../../api/stats';

// Mock the API
jest.mock('../../api/stats');

const mockStats = {
  totalInvites: 100,
  activeTasks: 5,
  successRate: '80%',
  totalPosts: 50,
};

describe('Dashboard', () => {
  const queryClient = new QueryClient();

  beforeEach(() => {
    (getStats as jest.Mock).mockResolvedValue(mockStats);
  });

  it('renders without crashing', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Dashboard />
      </QueryClientProvider>
    );

    expect(screen.getByText('Loading...')).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText('Total Invites')).toBeInTheDocument();
      expect(screen.getByText('100')).toBeInTheDocument();
      expect(screen.getByText('Active Tasks')).toBeInTheDocument();
      expect(screen.getByText('5')).toBeInTheDocument();
      expect(screen.getByText('Success Rate')).toBeInTheDocument();
      expect(screen.getByText('80%')).toBeInTheDocument();
      expect(screen.getByText('Total Posts')).toBeInTheDocument();
      expect(screen.getByText('50')).toBeInTheDocument();
    });
  });

  it('handles API error', async () => {
    (getStats as jest.Mock).mockRejectedValue(new Error('API Error'));

    render(
      <QueryClientProvider client={queryClient}>
        <Dashboard />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Total Invites')).toBeInTheDocument();
      expect(screen.getByText('0')).toBeInTheDocument();
      expect(screen.getByText('Active Tasks')).toBeInTheDocument();
      expect(screen.getByText('0')).toBeInTheDocument();
      expect(screen.getByText('Success Rate')).toBeInTheDocument();
      expect(screen.getByText('0%')).toBeInTheDocument();
      expect(screen.getByText('Total Posts')).toBeInTheDocument();
      expect(screen.getByText('0')).toBeInTheDocument();
    });
  });
}); 