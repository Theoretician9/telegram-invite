import axios from 'axios';

const api = axios.create({
  baseURL: '/api/invite',
});

export interface InviteRequest {
  target: string;
  message: string;
}

export interface InviteStatus {
  task_id: string;
  status: string;
  progress: number;
  total: number;
  success: number;
  failed: number;
  created_at: string;
  updated_at: string;
}

export async function startInvite(data: InviteRequest): Promise<InviteStatus> {
  const { data: response } = await api.post<InviteStatus>('/start', data);
  return response;
}

export async function getInviteStatus(): Promise<InviteStatus> {
  const { data } = await api.get<InviteStatus>('/status');
  return data;
}

export async function stopInvite(taskId: string): Promise<void> {
  await api.post(`/stop/${taskId}`);
} 