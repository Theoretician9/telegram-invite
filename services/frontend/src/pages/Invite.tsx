import { useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Grid,
  TextField,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from 'react-query';
import { startInvite, getInviteStatus } from '../api/invite';

export default function Invite() {
  const [target, setTarget] = useState('');
  const [message, setMessage] = useState('');

  const { mutate: startInviteTask, isLoading } = useMutation(startInvite, {
    onSuccess: (data) => {
      // Start polling for status
      refetch();
    },
  });

  const { data: status, refetch } = useQuery(
    'inviteStatus',
    () => getInviteStatus(),
    {
      enabled: false,
      refetchInterval: 5000,
    }
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    startInviteTask({ target, message });
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Invite Users
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
                <Button
                  type="submit"
                  variant="contained"
                  color="primary"
                  disabled={isLoading}
                  sx={{ mt: 2 }}
                >
                  {isLoading ? 'Starting...' : 'Start Invite'}
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
                    Success: {status.success}
                  </Typography>
                  <Typography>
                    Failed: {status.failed}
                  </Typography>
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
} 