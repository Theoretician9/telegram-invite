import { render, screen, fireEvent } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import Layout from '../Layout';

describe('Layout', () => {
  it('renders without crashing', () => {
    render(
      <BrowserRouter>
        <Layout>
          <div>Test Content</div>
        </Layout>
      </BrowserRouter>
    );

    expect(screen.getByText('Telegram Invite')).toBeInTheDocument();
    expect(screen.getByText('Test Content')).toBeInTheDocument();
  });

  it('renders all menu items', () => {
    render(
      <BrowserRouter>
        <Layout>
          <div>Test Content</div>
        </Layout>
      </BrowserRouter>
    );

    expect(screen.getByText('Dashboard')).toBeInTheDocument();
    expect(screen.getByText('Invite')).toBeInTheDocument();
    expect(screen.getByText('Parser')).toBeInTheDocument();
    expect(screen.getByText('Autopost')).toBeInTheDocument();
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('toggles mobile drawer', () => {
    render(
      <BrowserRouter>
        <Layout>
          <div>Test Content</div>
        </Layout>
      </BrowserRouter>
    );

    const menuButton = screen.getByLabelText('open drawer');
    fireEvent.click(menuButton);

    expect(screen.getByText('Dashboard')).toBeVisible();
    expect(screen.getByText('Invite')).toBeVisible();
    expect(screen.getByText('Parser')).toBeVisible();
    expect(screen.getByText('Autopost')).toBeVisible();
    expect(screen.getByText('Settings')).toBeVisible();
  });
}); 