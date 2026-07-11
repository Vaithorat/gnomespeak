import AsyncStorage from '@react-native-async-storage/async-storage';
import {AppSettings} from '../types';

const KEYS = {
  SERVER_URL: '@voicetalk/server_url',
  OPENAI_KEY: '@voicetalk/openai_key',
  GEMINI_KEY: '@voicetalk/gemini_key',
  OPENCODE_KEY: '@voicetalk/opencode_key',
  OPENROUTER_KEY: '@voicetalk/openrouter_key',
};

export async function loadSettings(): Promise<AppSettings> {
  const [serverUrl, openaiKey, geminiKey, opencodeKey, openrouterKey] = await Promise.all([
    AsyncStorage.getItem(KEYS.SERVER_URL),
    AsyncStorage.getItem(KEYS.OPENAI_KEY),
    AsyncStorage.getItem(KEYS.GEMINI_KEY),
    AsyncStorage.getItem(KEYS.OPENCODE_KEY),
    AsyncStorage.getItem(KEYS.OPENROUTER_KEY),
  ]);

  return {
    serverUrl: serverUrl || '192.168.1.100:8765',
    openaiKey: openaiKey || '',
    geminiKey: geminiKey || '',
    opencodeKey: opencodeKey || '',
    openrouterKey: openrouterKey || '',
  };
}

export async function saveSettings(settings: AppSettings): Promise<void> {
  await Promise.all([
    AsyncStorage.setItem(KEYS.SERVER_URL, settings.serverUrl),
    AsyncStorage.setItem(KEYS.OPENAI_KEY, settings.openaiKey),
    AsyncStorage.setItem(KEYS.GEMINI_KEY, settings.geminiKey),
    AsyncStorage.setItem(KEYS.OPENCODE_KEY, settings.opencodeKey),
    AsyncStorage.setItem(KEYS.OPENROUTER_KEY, settings.openrouterKey),
  ]);
}

export async function clearSettings(): Promise<void> {
  await AsyncStorage.multiRemove([
    KEYS.SERVER_URL,
    KEYS.OPENAI_KEY,
    KEYS.GEMINI_KEY,
    KEYS.OPENCODE_KEY,
    KEYS.OPENROUTER_KEY,
  ]);
}
