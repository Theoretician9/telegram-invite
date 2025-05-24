import { useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Grid,
  TextField,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
} from '@mui/material';
import { useMutation, useQuery } from 'react-query';
import { startParser, getParserStatus, downloadResults } from '../api/parser';

export default function Parser() {
  const [source, setSource] = useState('');
  const [limit, setLimit] = useState('1000');

  const { mutate: startParserTask, isLoading } = useMutation(startParser, {
    onSuccess: (data) => {
      // Start polling for status
      refetch();
    },
  });

  const { data: status, refetch } = useQuery(
    'parserStatus',
    () => getParserStatus(),
    {
      enabled: false,
      refetchInterval: 5000,
    }
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    startParserTask({ source, limit: parseInt(limit) });
  };

  const handleDownload = async () => {
    if (status?.task_id) {
      const blob = await downloadResults(status.task_id);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `parser-results-${status.task_id}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    }
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        User Parser
      </Typography>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <form onSubmit={handleSubmit}>
                <TextField
                  fullWidth
                  label="Source Chat"
                  value={source}
                  onChange={(e) => setSource(e.target.value)}
                  margin="normal"
                  required
                />
                <TextField
                  fullWidth
                  label="Limit"
                  type="number"
                  value={limit}
                  onChange={(e) => setLimit(e.target.value)}
                  margin="normal"
                  required
                />
                <Button
                  type="submit"
                  variant="contained"
                  color="primary"
                  disabled={isLoading}
                  sx={{ mt: 2 }}
                >
                  {isLoading ? 'Starting...' : 'Start Parser'}
                </Button>
              </form>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Status
              </Typography>
              {status ? (
                <>
                  <Typography>
                    Status: {status.status}
                  </Typography>
                  <Typography>
                    Progress: {status.progress} / {status.total}
                  </Typography>
                  <Typography>
                    Found: {status.found}
                  </Typography>
                  {status.status === 'completed' && (
                    <Button
                      variant="contained"
                      color="primary"
                      onClick={handleDownload}
                      sx={{ mt: 2 }}
                    >
                      Download Results
                    </Button>
                  )}
                </>
              ) : (
                <Typography>No active task</Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        {status?.results && (
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  Results Preview
                </Typography>
                <TableContainer component={Paper}>
                  <Table>
                    <TableHead>
                      <TableRow>
                        <TableCell>Username</TableCell>
                        <TableCell>First Name</TableCell>
                        <TableCell>Last Name</TableCell>
                        <TableCell>Phone</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {status.results.slice(0, 10).map((user, index) => (
                        <TableRow key={index}>
                          <TableCell>{user.username}</TableCell>
                          <TableCell>{user.first_name}</TableCell>
                          <TableCell>{user.last_name}</TableCell>
                          <TableCell>{user.phone}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </CardContent>
            </Card>
          </Grid>
        )}
      </Grid>
    </Box>
  );
} 