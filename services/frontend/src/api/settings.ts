import axios from 'axios';

const api = axios.create({
  baseURL: '/api/settings',
});

export interface Settings {
  telegram_api_id: string;
  telegram_api_hash: string;
  jwt_secret: string;
}

export async function getSettings(): Promise<Settings> {
  const { data } = await api.get<Settings>('/');
  return data;
}

export async function updateSettings(settings: Settings): Promise<Settings> {
  const { data } = await api.put<Settings>('/', settings);
  return data;
} 