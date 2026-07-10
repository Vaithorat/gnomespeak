import {ResultMessage, QuestionMessage, ConnectionStatus} from '../types';

type ResultCallback = (result: ResultMessage) => void;
type QuestionCallback = (question: QuestionMessage) => void;
type StatusCallback = (status: ConnectionStatus) => void;

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const PING_INTERVAL_MS = 30000;

export class WebSocketService {
  private ws: WebSocket | null = null;
  private url: string = '';
  private apiKey: string = '';
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts: number = 0;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private resultCallback: ResultCallback | null = null;
  private questionCallback: QuestionCallback | null = null;
  private statusCallback: StatusCallback | null = null;
  private shouldReconnect: boolean = true;

  onResult(callback: ResultCallback): void {
    this.resultCallback = callback;
  }

  onQuestion(callback: QuestionCallback): void {
    this.questionCallback = callback;
  }

  onStatusChange(callback: StatusCallback): void {
    this.statusCallback = callback;
  }

  connect(url: string, apiKey: string): void {
    this.url = url;
    this.apiKey = apiKey;
    this.shouldReconnect = true;
    this.reconnectAttempts = 0;
    this._connect();
  }

  disconnect(): void {
    this.shouldReconnect = false;
    this._cleanup();
  }

  send(text: string): void {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      this._notifyStatus('error');
      return;
    }

    const message = JSON.stringify({
      type: 'command',
      text,
      api_key: this.apiKey,
    });

    this.ws.send(message);
  }

  sendAnswer(id: string, text: string): void {
    if (this.ws?.readyState !== WebSocket.OPEN) {
      return;
    }
    this.ws.send(JSON.stringify({type: 'answer', id, text}));
  }

  private _connect(): void {
    this._cleanup();
    this._notifyStatus('connecting');

    try {
      this.ws = new WebSocket(`ws://${this.url}`);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this._notifyStatus('connected');
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
            this.questionCallback?.(data);
          } else if (data.type === 'result') {
            this.resultCallback?.(data);
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
    if (!this.shouldReconnect) {
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

  private _notifyStatus(status: ConnectionStatus): void {
    this.statusCallback?.(status);
  }
}

export const wsService = new WebSocketService();
