export interface CommandMessage {
  type: 'command';
  text: string;
  api_key: string;
  provider?: string;
  session_id?: string;
}

export interface ConversationMessage {
  id: string;
  role: 'user' | 'assistant' | 'question';
  text: string;
  timestamp: number;
  isFinal?: boolean;
}

export interface ResultMessage {
  type: 'result';
  success: boolean;
  message: string;
}

export interface QuestionMessage {
  type: 'question';
  id: string;
  message: string;
  options: string[];
}

export interface AnswerMessage {
  type: 'answer';
  id: string;
  text: string;
}

export type ServerMessage = ResultMessage | QuestionMessage;

export interface CommandLogEntry {
  id: string;
  transcript: string;
  result: string;
  success: boolean;
  timestamp: number;
}

export type ConnectionStatus =
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'error';

export interface AppSettings {
  serverUrl: string;
  openaiKey: string;
  geminiKey: string;
  opencodeKey: string;
  openrouterKey: string;
}

export function getActiveProvider(settings: AppSettings): {apiKey: string; provider: string} {
  if (settings.geminiKey) return {apiKey: settings.geminiKey, provider: 'gemini'};
  if (settings.openrouterKey) return {apiKey: settings.openrouterKey, provider: 'openrouter'};
  if (settings.opencodeKey) return {apiKey: settings.opencodeKey, provider: 'opencode'};
  if (settings.openaiKey) return {apiKey: settings.openaiKey, provider: 'openai'};
  return {apiKey: '', provider: 'openai'};
}
