import {ResultMessage, QuestionMessage, ConnectionStatus, StreamChunkMessage, StreamResultMessage, CommandMessage} from '../types';

type ResultCallback = (result: ResultMessage) => void;
type QuestionCallback = (question: QuestionMessage) => void;
type StatusCallback = (status: ConnectionStatus) => void;
type ConnectedCallback = (serverUrl: string) => void;
type StreamChunkCallback = (chunk: StreamChunkMessage) => void;
type StreamResultCallback = (result: StreamResultMessage) => void;
type Unsubscribe = () => void;

export type SendStatus = {
  ok: boolean;
  error?: string;
};

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const PING_INTERVAL_MS = 30000;

export class WebSocketService {
  private ws: WebSocket | null = null;
  private url: string = '';
  private apiKey: string = '';
  private provider: string = 'openai';
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts: number = 0;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private resultCallbacks = new Set<ResultCallback>();
  private questionCallbacks = new Set<QuestionCallback>();
  private statusCallbacks = new Set<StatusCallback>();
  private connectedCallbacks = new Set<ConnectedCallback>();
  private streamChunkCallbacks = new Set<StreamChunkCallback>();
  private streamResultCallbacks = new Set<StreamResultCallback>();
  private shouldReconnect: boolean = true;
  private reconnectBlockedByInvalidUrl: boolean = false;

  onResult(callback: ResultCallback): Unsubscribe {
    this.resultCallbacks.add(callback);
    return () => this.resultCallbacks.delete(callback);
  }

  onQuestion(callback: QuestionCallback): Unsubscribe {
    this.questionCallbacks.add(callback);
    return () => this.questionCallbacks.delete(callback);
  }

  onStatusChange(callback: StatusCallback): Unsubscribe {
    this.statusCallbacks.add(callback);
    return () => this.statusCallbacks.delete(callback);
  }

  onConnected(callback: ConnectedCallback): Unsubscribe {
    this.connectedCallbacks.add(callback);
    return () => this.connectedCallbacks.delete(callback);
  }

  onStreamChunk(callback: StreamChunkCallback): Unsubscribe {
    this.streamChunkCallbacks.add(callback);
    return () => this.streamChunkCallbacks.delete(callback);
  }

  onStreamResult(callback: StreamResultCallback): Unsubscribe {
    this.streamResultCallbacks.add(callback);
    return () => this.streamResultCallbacks.delete(callback);
  }

  connect(url: string, apiKey: string, provider: string = 'openai'): void {
    this.url = url;
    this.apiKey = apiKey;
    this.provider = provider;
    this.shouldReconnect = true;
    this.reconnectBlockedByInvalidUrl = false;
    this.reconnectAttempts = 0;
    this._connect();
  }

  disconnect(): void {
    this.shouldReconnect = false;
    this._cleanup();
  }

  send(text: string, sessionId?: string, requestId?: string, alternatives?: string[]): SendStatus {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      return {ok: false, error: 'Not connected to server.'};
    }

    const msg: CommandMessage = {
      type: 'command',
      text,
      api_key: this.apiKey,
      provider: this.provider,
    };
    if (sessionId) {
      msg.session_id = sessionId;
    }
    if (requestId) {
      msg.request_id = requestId;
    }
    if (alternatives && alternatives.length > 0) {
      msg.alternatives = alternatives;
    }

    return this._sendJson(msg);
  }

  sendWithSession(text: string, sessionId: string, requestId?: string, alternatives?: string[]): SendStatus {
    return this.send(text, sessionId, requestId, alternatives);
  }

  sendAnswer(id: string, text: string, requestId?: string): SendStatus {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      return {ok: false, error: 'Not connected to server.'};
    }
    const msg: Record<string, string> = {type: 'answer', id, text};
    if (requestId) {
      msg.request_id = requestId;
    }
    return this._sendJson(msg);
  }

  private _normalizeUrl(raw: string): string {
    let u = raw.trim();
    if (u.startsWith('ws://') || u.startsWith('wss://')) {
      return u;
    }
    if (u.startsWith('https://')) {
      return u.replace(/^https:\/\//, 'wss://');
    }
    if (u.startsWith('http://')) {
      return u.replace(/^http:\/\//, 'ws://');
    }
    return `ws://${u}`;
  }

  private _isValidUrl(raw: string): boolean {
    try {
      const normalized = this._normalizeUrl(raw);
      const parsed = new URL(normalized);
      return (
        (parsed.protocol === 'ws:' || parsed.protocol === 'wss:') &&
        parsed.hostname.length > 0
      );
    } catch {
      return false;
    }
  }

  private _connect(): void {
    this._cleanup();
    this._notifyStatus('connecting');

    if (!this._isValidUrl(this.url)) {
      this.reconnectBlockedByInvalidUrl = true;
      this.shouldReconnect = false;
      this._notifyStatus('error');
      return;
    }

    const wsUrl = this._normalizeUrl(this.url);

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this._notifyStatus('connected');
        this.connectedCallbacks.forEach(callback => callback(this._normalizeUrl(this.url)));
        this._startPing();
      };

      this.ws.onclose = () => {
        this._notifyStatus('disconnected');
        this._scheduleReconnect();
      };

      this.ws.onerror = () => {
        this._notifyStatus('error');
      };

      this.ws.onmessage = (event) => {
        try {
          const raw = event.data;
          if (!raw) { return; }
          const data = JSON.parse(raw);
          if (data.type === 'question') {
            if (typeof data.id === 'string' && typeof data.message === 'string' && Array.isArray(data.options)) {
              this.questionCallbacks.forEach(callback => callback(data));
            }
          } else if (data.type === 'stream_chunk') {
            if (typeof data.content === 'string') {
              this.streamChunkCallbacks.forEach(callback => callback(data));
            }
          } else if (data.type === 'stream_result') {
            if (typeof data.message === 'string' && typeof data.success === 'boolean') {
              this.streamResultCallbacks.forEach(callback => callback(data));
            }
          } else if (data.type === 'result') {
            if (typeof data.message === 'string' && typeof data.success === 'boolean') {
              this.resultCallbacks.forEach(callback => callback(data));
            }
          }
        } catch {
          // Ignore invalid messages
        }
      };
    } catch {
      this._notifyStatus('error');
      this._scheduleReconnect();
    }
  }

  private _scheduleReconnect(): void {
    if (!this.shouldReconnect || this.reconnectBlockedByInvalidUrl) {
      return;
    }

    const delay = Math.min(
      RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempts),
      RECONNECT_MAX_MS,
    );

    this.reconnectTimer = setTimeout(() => {
      this.reconnectAttempts++;
      this._connect();
    }, delay);
  }

  private _startPing(): void {
    this.pingTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({type: 'ping'}));
      }
    }, PING_INTERVAL_MS);
  }

  private _cleanup(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      this.ws.onmessage = null;
      if (
        this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING
      ) {
        this.ws.close();
      }
      this.ws = null;
    }
  }

  private _sendJson(payload: object): SendStatus {
    try {
      this.ws?.send(JSON.stringify(payload));
      return {ok: true};
    } catch {
      return {ok: false, error: 'Failed to send message.'};
    }
  }

  private _notifyStatus(status: ConnectionStatus): void {
    this.statusCallbacks.forEach(callback => callback(status));
  }
}

export const wsService = new WebSocketService();
