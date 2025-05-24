import { Grid, Card, CardContent, Typography } from '@mui/material';
import { useQuery } from 'react-query';
import { getStats } from '../api/stats';

export default function Dashboard() {
  const { data: stats, isLoading } = useQuery('stats', getStats);

  if (isLoading) {
    return <Typography>Loading...</Typography>;
  }

  return (
    <Grid container spacing={3}>
      <Grid item xs={12} md={6} lg={3}>
        <Card>
          <CardContent>
            <Typography color="textSecondary" gutterBottom>
              Total Invites
            </Typography>
            <Typography variant="h5">
              {stats?.totalInvites || 0}
            </Typography>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} md={6} lg={3}>
        <Card>
          <CardContent>
            <Typography color="textSecondary" gutterBottom>
              Active Tasks
            </Typography>
            <Typography variant="h5">
              {stats?.activeTasks || 0}
            </Typography>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} md={6} lg={3}>
        <Card>
          <CardContent>
            <Typography color="textSecondary" gutterBottom>
              Success Rate
            </Typography>
            <Typography variant="h5">
              {stats?.successRate || '0%'}
            </Typography>
          </CardContent>
        </Card>
      </Grid>
      <Grid item xs={12} md={6} lg={3}>
        <Card>
          <CardContent>
            <Typography color="textSecondary" gutterBottom>
              Total Posts
            </Typography>
            <Typography variant="h5">
              {stats?.totalPosts || 0}
            </Typography>
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  );
} 