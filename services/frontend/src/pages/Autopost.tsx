import React, { useState } from 'react';
import {
  Box,
  Card,
  CardContent,
  Typography,
  TextField,
  Button,
  Grid,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  CircularProgress,
} from '@mui/material';
import { useQuery, useMutation } from 'react-query';
import { startAutopost, getAutopostStatus, stopAutopost } from '../api/autopost';

const Autopost: React.FC = () => {
  const [target, setTarget] = useState('');
  const [message, setMessage] = useState('');
  const [interval, setInterval] = useState('1h');

  const { data: status, isLoading } = useQuery('autopostStatus', getAutopostStatus, {
    refetchInterval: 5000,
  });

  const startMutation = useMutation(startAutopost, {
    onSuccess: () => {
      setTarget('');
      setMessage('');
    },
  });

  const stopMutation = useMutation(stopAutopost);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    startMutation.mutate({
      target,
      message,
      interval,
    });
  };

  const handleStop = () => {
    if (status?.task_id) {
      stopMutation.mutate(status.task_id);
    }
  };

  if (isLoading) {
    return (
      <Box display="flex" justifyContent="center" alignItems="center" minHeight="200px">
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box p={3}>
      <Typography variant="h4" gutterBottom>
        Autopost
      </Typography>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <form onSubmit={handleSubmit}>
                <TextField
                  fullWidth
                  label="Target Chat"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  margin="normal"
                  required
                />
                <TextField
                  fullWidth
                  label="Message"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  margin="normal"
                  required
                  multiline
                  rows={4}
                />
                <FormControl fullWidth margin="normal">
                  <InputLabel>Interval</InputLabel>
                  <Select
                    value={interval}
                    onChange={(e) => setInterval(e.target.value)}
                    label="Interval"
                  >
                    <MenuItem value="30m">30 minutes</MenuItem>
                    <MenuItem value="1h">1 hour</MenuItem>
                    <MenuItem value="2h">2 hours</MenuItem>
                    <MenuItem value="4h">4 hours</MenuItem>
                    <MenuItem value="6h">6 hours</MenuItem>
                    <MenuItem value="12h">12 hours</MenuItem>
                    <MenuItem value="24h">24 hours</MenuItem>
                  </Select>
                </FormControl>
                <Box mt={2}>
                  <Button
                    type="submit"
                    variant="contained"
                    color="primary"
                    disabled={startMutation.isLoading}
                  >
                    Start Autopost
                  </Button>
                </Box>
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
                  <Typography>Status: {status.status}</Typography>
                  <Typography>Last post: {new Date(status.last_post).toLocaleString()}</Typography>
                  <Typography>Next post: {new Date(status.next_post).toLocaleString()}</Typography>
                  <Box mt={2}>
                    <Button
                      variant="contained"
                      color="secondary"
                      onClick={handleStop}
                      disabled={stopMutation.isLoading || status.status !== 'running'}
                    >
                      Stop Autopost
                    </Button>
                  </Box>
                </>
              ) : (
                <Typography>No active task</Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
};

export default Autopost; 