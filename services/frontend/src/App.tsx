import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { ThemeProvider, CssBaseline } from '@mui/material';
import { QueryClient, QueryClientProvider } from 'react-query';
import theme from './theme';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Invite from './pages/Invite';
import Parser from './pages/Parser';
import Autopost from './pages/Autopost';
import Settings from './pages/Settings';

const queryClient = new QueryClient();

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <Router>
          <Layout>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/invite" element={<Invite />} />
              <Route path="/parser" element={<Parser />} />
              <Route path="/autopost" element={<Autopost />} />
              <Route path="/settings" element={<Settings />} />
            </Routes>
          </Layout>
        </Router>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App; 