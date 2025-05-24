import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
});

export interface Stats {
  totalInvites: number;
  activeTasks: number;
  successRate: string;
  totalPosts: number;
}

export async function getStats(): Promise<Stats> {
  const { data } = await api.get<Stats>('/stats');
  return data;
} 