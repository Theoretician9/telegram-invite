import axios from 'axios';

const api = axios.create({
  baseURL: '/api/parser',
});

export interface ParserRequest {
  source: string;
  limit: number;
}

export interface ParserStatus {
  task_id: string;
  status: string;
  progress: number;
  total: number;
  found: number;
  results?: ParserResult[];
  created_at: string;
  updated_at: string;
}

export interface ParserResult {
  username: string;
  first_name: string;
  last_name: string;
  phone: string;
}

export async function startParser(data: ParserRequest): Promise<ParserStatus> {
  const { data: response } = await api.post<ParserStatus>('/start', data);
  return response;
}

export async function getParserStatus(): Promise<ParserStatus> {
  const { data } = await api.get<ParserStatus>('/status');
  return data;
}

export async function downloadResults(taskId: string): Promise<Blob> {
  const { data } = await api.get(`/download/${taskId}`, {
    responseType: 'blob',
  });
  return data;
} 