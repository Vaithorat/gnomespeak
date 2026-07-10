import AsyncStorage from '@react-native-async-storage/async-storage';
import {AppSettings} from '../types';

const KEYS = {
  SERVER_URL: '@voicetalk/server_url',
  API_KEY: '@voicetalk/api_key',
};

export async function loadSettings(): Promise<AppSettings> {
  const [serverUrl, apiKey] = await Promise.all([
    AsyncStorage.getItem(KEYS.SERVER_URL),
    AsyncStorage.getItem(KEYS.API_KEY),
  ]);

  return {
    serverUrl: serverUrl || '192.168.1.100:8765',
    apiKey: apiKey || '',
  };
}

export async function saveSettings(settings: AppSettings): Promise<void> {
  await Promise.all([
    AsyncStorage.setItem(KEYS.SERVER_URL, settings.serverUrl),
    AsyncStorage.setItem(KEYS.API_KEY, settings.apiKey),
  ]);
}

export async function clearSettings(): Promise<void> {
  await AsyncStorage.multiRemove([KEYS.SERVER_URL, KEYS.API_KEY]);
}
