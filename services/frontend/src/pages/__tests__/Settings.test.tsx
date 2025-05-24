import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from 'react-query';
import Settings from '../Settings';
import { updateSettings, getSettings } from '../../api/settings';

// Mock the API
jest.mock('../../api/settings');

const mockSettings = {
  telegram_api_id: '12345',
  telegram_api_hash: 'abcdef123456',
  jwt_secret: 'secret123',
};

describe('Settings', () => {
  const queryClient = new QueryClient();

  beforeEach(() => {
    (getSettings as jest.Mock).mockResolvedValue(mockSettings);
    (updateSettings as jest.Mock).mockResolvedValue(mockSettings);
  });

  it('renders without crashing', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Settings />
      </QueryClientProvider>
    );

    expect(screen.getByText('Settings')).toBeInTheDocument();
    expect(screen.getByText('Telegram API')).toBeInTheDocument();
    expect(screen.getByText('Security')).toBeInTheDocument();
    expect(screen.getByText('About')).toBeInTheDocument();
  });

  it('loads and displays current settings', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Settings />
      </QueryClientProvider>
    );

    await waitFor(() => {
      expect(screen.getByLabelText('API ID')).toHaveValue('12345');
      expect(screen.getByLabelText('API Hash')).toHaveValue('abcdef123456');
      expect(screen.getByLabelText('JWT Secret')).toHaveValue('secret123');
    });
  });

  it('handles form submission', async () => {
    render(
      <QueryClientProvider client={queryClient}>
        <Settings />
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByLabelText('API ID'), {
      target: { value: '54321' },
    });
    fireEvent.change(screen.getByLabelText('API Hash'), {
      target: { value: '654321fedcba' },
    });
    fireEvent.change(screen.getByLabelText('JWT Secret'), {
      target: { value: 'newsecret' },
    });

    fireEvent.click(screen.getByText('Save Settings'));

    await waitFor(() => {
      expect(updateSettings).toHaveBeenCalledWith({
        telegram_api_id: '54321',
        telegram_api_hash: '654321fedcba',
        jwt_secret: 'newsecret',
      });
    });

    await waitFor(() => {
      expect(screen.getByText('Settings updated successfully')).toBeInTheDocument();
    });
  });

  it('handles API error', async () => {
    (updateSettings as jest.Mock).mockRejectedValue(new Error('API Error'));

    render(
      <QueryClientProvider client={queryClient}>
        <Settings />
      </QueryClientProvider>
    );

    fireEvent.change(screen.getByLabelText('API ID'), {
      target: { value: '54321' },
    });
    fireEvent.click(screen.getByText('Save Settings'));

    await waitFor(() => {
      expect(screen.getByText('API Error')).toBeInTheDocument();
    });
  });
}); 