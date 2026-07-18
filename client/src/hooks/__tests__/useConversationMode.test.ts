import React from 'react';
import TestRenderer, {act} from 'react-test-renderer';
import {useConversationMode} from '../useConversationMode';

jest.mock('react-native', () => ({
  AppState: {
    currentState: 'active',
    addEventListener: jest.fn(() => ({remove: jest.fn()})),
  },
}));

const mockAppState = jest.requireMock('react-native').AppState as {
  currentState: string;
  addEventListener: jest.Mock;
};

jest.mock('@react-native-voice/voice', () => ({
  __esModule: true,
  default: {
    start: jest.fn().mockResolvedValue(undefined),
    stop: jest.fn().mockResolvedValue(undefined),
    destroy: jest.fn().mockResolvedValue(undefined),
    onSpeechStart: null,
    onSpeechEnd: null,
    onSpeechResults: null,
    onSpeechError: null,
  },
}));

const mockVoice = jest.requireMock('@react-native-voice/voice').default as {
  start: jest.Mock;
  stop: jest.Mock;
  destroy: jest.Mock;
  onSpeechStart: null | ((event: unknown) => void);
  onSpeechEnd: null | ((event: unknown) => void);
  onSpeechResults: null | ((event: {value?: string[]}) => void);
  onSpeechError: null | ((event: unknown) => void);
};

jest.mock('../../services/websocket', () => ({
  wsService: {
    sendWithSession: jest.fn(
      (_text: string, _sessionId: string, _requestId?: string) => ({ok: true}),
    ),
    sendAnswer: jest.fn(
      (_id: string, _text: string, _requestId?: string) => ({ok: true}),
    ),
  },
}));

const mockWsService = jest.requireMock('../../services/websocket').wsService as {
  sendWithSession: jest.Mock;
  sendAnswer: jest.Mock;
};

type HookValue = ReturnType<typeof useConversationMode>;

let latestHook: HookValue;

function HookHarness() {
  latestHook = useConversationMode();
  return null;
}

describe('useConversationMode', () => {
  let renderer: TestRenderer.ReactTestRenderer | null;

  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    mockAppState.currentState = 'active';
    mockAppState.addEventListener.mockReturnValue({remove: jest.fn()});
    mockVoice.onSpeechStart = null;
    mockVoice.onSpeechEnd = null;
    mockVoice.onSpeechResults = null;
    mockVoice.onSpeechError = null;
    renderer = null;
  });

  afterEach(async () => {
    if (renderer) {
      await act(async () => {
        renderer!.unmount();
      });
    }
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
  });

  async function mountHook() {
    await act(async () => {
      renderer = TestRenderer.create(React.createElement(HookHarness));
    });
  }

  test('sends clarification answers with the matching request id', async () => {
    await mountHook();

    await act(async () => {
      await latestHook.start();
    });

    const speechResults = mockVoice.onSpeechResults;

    expect(typeof speechResults).toBe('function');

    await act(async () => {
      await latestHook.stop();
    });

    await act(async () => {
      latestHook.handleStreamQuestion('question-1', 'Which one?', 'req_q1');
      speechResults?.({value: ['option a']});
      jest.advanceTimersByTime(1500);
      await Promise.resolve();
    });

    expect(mockWsService.sendAnswer).toHaveBeenCalledWith(
      'question-1',
      'option a',
      'req_q1',
    );
  });

  test('routes stream chunks and results only to the matching request', async () => {
    await mountHook();

    await act(async () => {
      await latestHook.start();
    });

    expect(typeof mockVoice.onSpeechResults).toBe('function');

    await act(async () => {
      mockVoice.onSpeechResults?.({value: ['open youtube', 'open you tube']});
      jest.advanceTimersByTime(1500);
      await Promise.resolve();
    });

    expect(mockWsService.sendWithSession).toHaveBeenCalledTimes(1);
    expect(mockWsService.sendWithSession).toHaveBeenCalledWith(
      'open youtube',
      expect.any(String),
      expect.any(String),
      ['open youtube', 'open you tube'],
    );
    const requestId = mockWsService.sendWithSession.mock.calls[0]?.[2];

    expect(typeof requestId).toBe('string');

    act(() => {
      latestHook.handleStreamChunk('ignored', 'unknown_request');
      latestHook.handleStreamChunk('Opened YouTube', requestId);
    });

    expect(latestHook.messages[1].text).toBe('Opened YouTube');

    act(() => {
      latestHook.handleStreamResult('ignored', true, 'unknown_request');
    });

    expect(latestHook.messages).toHaveLength(3);
    expect(latestHook.messages[2].text).toBe('ignored');

    act(() => {
      latestHook.handleStreamResult('Done.', true, requestId);
    });

    expect(latestHook.messages).toHaveLength(3);
    expect(latestHook.messages[1].role).toBe('assistant');
    expect(latestHook.messages[1].text).toBe('Opened YouTube');
  });

  test('shows a final assistant message even if request tracking was lost', async () => {
    await mountHook();

    act(() => {
      latestHook.handleStreamResult(
        'Bluetooth radio control is not supported on this Windows setup.',
        true,
        'missing_request',
      );
    });

    expect(latestHook.messages).toHaveLength(1);
    expect(latestHook.messages[0].role).toBe('assistant');
    expect(latestHook.messages[0].text).toBe(
      'Bluetooth radio control is not supported on this Windows setup.',
    );
    expect(latestHook.liveText).toBe('');
  });
});
