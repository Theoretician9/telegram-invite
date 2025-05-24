import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from 'react-query';
import Parser from '../Parser';
import { startParser, getParserStatus, downloadResults } from '../../api/parser';

// Mock the API
jest.mock('../../api/parser');

const mockStatus = {
  task_id: '123',
  status: 'running',
  progress: 5,
  total: 10,
  found: 3,
  results: [
    {
      username: 'user1',
      first_name: 'John',
      last_name: 'Doe',
      phone: '+1234567890',
    },
  ],
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
};

describe('Parser', () => {
  const queryClient = new QueryClient();

  beforeEach(() => {
    (startParser as jest.Mock).mockResolvedValue(mockStatus);
    (getParserStatus as jest.Mock).mockResolvedValue(mockStatus);
    (downloadResults as jest.Mock).mockResolvedValue(new Blob(['test data']));
  });

  it('renders without crashing', () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Parser />
      </QueryClientProvider>
    );

    expect(screen.getByText('Parser')).toBeInTheDocument();
    expect(screen.getByLabelText('Source')).toBeInTheDocument();
    expect(screen.getByLabelText('Limit')).toBeInTheDocument();
    expect(screen.getByText('Start Parser')).toBeInTheDocument();
  });

  it('handles form submission', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Parser />
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByLabelText('Source'), {
      target: { value: 'test_chat' },
    });
    fireEvent.change(screen.getByLabelText('Limit'), {
      target: { value: '100' },
    });
    fireEvent.click(screen.getByText('Start Parser'));

    await waitFor(() => {
      expect(startParser).toHaveBeenCalledWith({
        source: 'test_chat',
        limit: 100,
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Status: running')).toBeInTheDocument();
      expect(screen.getByText('Progress: 5 / 10')).toBeInTheDocument();
      expect(screen.getByText('Found: 3')).toBeInTheDocument();
    });
  });

  it('handles API error', async () => {
    (startParser as jest.Mock).mockRejectedValue(new Error('API Error'));

    render(
      <QueryClientProvider client={queryClient}>
        <Parser />
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByLabelText('Source'), {
      target: { value: 'test_chat' },
    });
    fireEvent.click(screen.getByText('Start Parser'));

    await waitFor(() => {
      expect(screen.getByText('No active task')).toBeInTheDocument();
    });
  });

  it('displays results table when available', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Parser />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByText('Username')).toBeInTheDocument();
      expect(screen.getByText('First Name')).toBeInTheDocument();
      expect(screen.getByText('Last Name')).toBeInTheDocument();
      expect(screen.getByText('Phone')).toBeInTheDocument();
      expect(screen.getByText('user1')).toBeInTheDocument();
      expect(screen.getByText('John')).toBeInTheDocument();
      expect(screen.getByText('Doe')).toBeInTheDocument();
      expect(screen.getByText('+1234567890')).toBeInTheDocument();
    });
  });
}); 