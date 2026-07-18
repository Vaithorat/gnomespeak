import {afterEach, beforeEach, describe, expect, jest, test} from '@jest/globals';

import {WebSocketService} from '../websocket';

class MockWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.CONNECTING;
  onopen: null | (() => void) = null;
  onclose: null | (() => void) = null;
  onerror: null | (() => void) = null;
  onmessage: null | ((event: {data: string}) => void) = null;
  sent: string[] = [];
  closed = false;

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.closed = true;
    this.readyState = 3;
  }

  emitOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  emitMessage(data: unknown) {
    this.onmessage?.({data: JSON.stringify(data)});
  }

  emitInvalidMessage(raw = '{') {
    this.onmessage?.({data: raw});
  }
}

describe('WebSocketService', () => {
  let originalWebSocket: typeof globalThis.WebSocket | undefined;
  let services: WebSocketService[];

  beforeEach(() => {
    originalWebSocket = globalThis.WebSocket;
    MockWebSocket.instances = [];
    services = [];
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
  });

  afterEach(() => {
    services.forEach(service => service.disconnect());
    if (originalWebSocket) {
      globalThis.WebSocket = originalWebSocket;
    } else {
      // @ts-expect-error test cleanup for environments without WebSocket
      delete globalThis.WebSocket;
    }
    jest.restoreAllMocks();
  });

  const createService = () => {
    const service = new WebSocketService();
    services.push(service);
    return service;
  };

  test('fan-outs result listeners and unsubscribes cleanly', () => {
    const service = createService();
    const first = jest.fn();
    const second = jest.fn();
    const offFirst = service.onResult(first);
    service.onResult(second);

    service.connect('127.0.0.1:8765', 'key', 'openai');
    const socket = MockWebSocket.instances[0];
    socket.emitOpen();

    offFirst();
    socket.emitMessage({type: 'result', success: true, message: 'Done', request_id: 'r1'});

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledWith({
      type: 'result',
      success: true,
      message: 'Done',
      request_id: 'r1',
    });
  });

  test('rejects invalid urls without opening a socket or retrying', () => {
    const service = createService();
    const statuses: string[] = [];
    const timeoutSpy = jest.spyOn(globalThis, 'setTimeout');
    service.onStatusChange(status => statuses.push(status));

    service.connect('ws://', 'key', 'openai');

    expect(statuses).toEqual(['connecting', 'error']);
    expect(MockWebSocket.instances).toHaveLength(0);
    expect(timeoutSpy).not.toHaveBeenCalled();
  });

  test('routes only well-formed stream messages and reports send failure when disconnected', () => {
    const service = createService();
    const chunks: string[] = [];
    const results: string[] = [];

    service.onStreamChunk(chunk => chunks.push(chunk.content));
    service.onStreamResult(result => results.push(result.message));

    expect(service.sendWithSession('hello', 's1', 'r1')).toEqual({
      ok: false,
      error: 'Not connected to server.',
    });

    service.connect('127.0.0.1:8765', 'key', 'openai');
    const socket = MockWebSocket.instances[0];
    socket.emitOpen();

    expect(service.sendWithSession('hello', 's1', 'r1', ['hello', 'hullo'])).toEqual({ok: true});
    expect(socket.sent).toContain(JSON.stringify({type: 'command', text: 'hello', api_key: 'key', provider: 'openai', session_id: 's1', request_id: 'r1', alternatives: ['hello', 'hullo']}));

    expect(service.sendAnswer('q1', 'yes', 'r1')).toEqual({ok: true});
    expect(socket.sent).toContain(JSON.stringify({type: 'answer', id: 'q1', text: 'yes', request_id: 'r1'}));

    socket.emitMessage({type: 'stream_chunk', content: 'hello', request_id: 'r1'});
    socket.emitMessage({type: 'stream_chunk', request_id: 'r1'});
    socket.emitInvalidMessage();
    socket.emitMessage({type: 'stream_result', success: true, message: 'done', request_id: 'r1'});
    socket.emitMessage({type: 'stream_result', success: true, request_id: 'r1'});

    expect(chunks).toEqual(['hello']);
    expect(results).toEqual(['done']);
  });
});
