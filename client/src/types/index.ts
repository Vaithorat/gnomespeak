export interface CommandMessage {
  type: 'command';
  text: string;
  api_key: string;
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
  apiKey: string;
}
