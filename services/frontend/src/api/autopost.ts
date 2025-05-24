import axios from 'axios';

const api = axios.create({
  baseURL: '/api/autopost',
});

export interface AutopostRequest {
  target: string;
  message: string;
  interval: number;
  enabled: boolean;
}

export interface AutopostStatus {
  task_id: string;
  status: string;
  enabled: boolean;
  interval: number;
  last_post_at: string;
  total_posts: number;
  posts?: AutopostPost[];
  created_at: string;
  updated_at: string;
}

export interface AutopostPost {
  id: number;
  message: string;
  status: string;
  created_at: string;
}

export async function startAutopost(data: AutopostRequest): Promise<AutopostStatus> {
  const { data: response } = await api.post<AutopostStatus>('/start', data);
  return response;
}

export async function getAutopostStatus(): Promise<AutopostStatus> {
  const { data } = await api.get<AutopostStatus>('/status');
  return data;
}

export async function stopAutopost(taskId: string): Promise<void> {
  await api.post(`/stop/${taskId}`);
} 