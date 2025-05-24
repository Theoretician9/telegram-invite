import axios from 'axios';

const api = axios.create({
  baseURL: '/api/autopost',
});

export interface AutopostRequest {
  target: string;
  message: string;
  interval: string;
}

export interface AutopostStatus {
  task_id: string;
  status: 'running' | 'stopped' | 'error';
  last_post: string;
  next_post: string;
  created_at: string;
  updated_at: string;
}

export const startAutopost = async (data: AutopostRequest): Promise<AutopostStatus> => {
  const response = await api.post<AutopostStatus>('/start', data);
  return response.data;
};

export const getAutopostStatus = async (): Promise<AutopostStatus> => {
  const response = await api.get<AutopostStatus>('/status');
  return response.data;
};

export const stopAutopost = async (taskId: string): Promise<void> => {
  await api.post(`/stop/${taskId}`);
}; 