import { useState } from 'react';
import {
  Box,
  Button,
  Card,
  CardContent,
  Grid,
  TextField,
  Typography,
  Alert,
} from '@mui/material';
import { useMutation } from 'react-query';
import { updateSettings, getSettings } from '../api/settings';

export default function Settings() {
  const [telegramApiId, setTelegramApiId] = useState('');
  const [telegramApiHash, setTelegramApiHash] = useState('');
  const [jwtSecret, setJwtSecret] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const { mutate: updateSettingsTask, isLoading } = useMutation(updateSettings, {
    onSuccess: () => {
      setSuccess('Settings updated successfully');
      setError(null);
    },
    onError: (error: Error) => {
      setError(error.message);
      setSuccess(null);
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    updateSettingsTask({
      telegram_api_id: telegramApiId,
      telegram_api_hash: telegramApiHash,
      jwt_secret: jwtSecret,
    });
  };

  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        Settings
      </Typography>

      <Grid container spacing={3}>
        <Grid item xs={12} md={8}>
          <Card>
            <CardContent>
              {error && (
                <Alert severity="error" sx={{ mb: 2 }}>
                  {error}
                </Alert>
              )}
              {success && (
                <Alert severity="success" sx={{ mb: 2 }}>
                  {success}
                </Alert>
              )}
              <form onSubmit={handleSubmit}>
                <Typography variant="h6" gutterBottom>
                  Telegram API
                </Typography>
                <TextField
                  fullWidth
                  label="API ID"
                  value={telegramApiId}
                  onChange={(e) => setTelegramApiId(e.target.value)}
                  margin="normal"
                  required
                />
                <TextField
                  fullWidth
                  label="API Hash"
                  value={telegramApiHash}
                  onChange={(e) => setTelegramApiHash(e.target.value)}
                  margin="normal"
                  required
                />

                <Typography variant="h6" gutterBottom sx={{ mt: 4 }}>
                  Security
                </Typography>
                <TextField
                  fullWidth
                  label="JWT Secret"
                  value={jwtSecret}
                  onChange={(e) => setJwtSecret(e.target.value)}
                  margin="normal"
                  required
                  type="password"
                />

                <Button
                  type="submit"
                  variant="contained"
                  color="primary"
                  disabled={isLoading}
                  sx={{ mt: 2 }}
                >
                  {isLoading ? 'Saving...' : 'Save Settings'}
                </Button>
              </form>
            </CardContent>
          </Card>
        </Grid>

        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                About
              </Typography>
              <Typography variant="body2" color="textSecondary" paragraph>
                Version: 1.0.0
              </Typography>
              <Typography variant="body2" color="textSecondary" paragraph>
                This application helps you manage Telegram invites, parse users,
                and automate posting.
              </Typography>
              <Typography variant="body2" color="textSecondary">
                Make sure to keep your API credentials secure and never share them
                with anyone.
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
} 