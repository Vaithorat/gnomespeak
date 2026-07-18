import React from 'react';
import TestRenderer, {act} from 'react-test-renderer';
import {Animated, TextInput} from 'react-native';

jest.mock('../../../App', () => {
  const ReactLocal = require('react');
  return {
    AppContext: ReactLocal.createContext({
      settings: {
        serverUrl: '',
        openaiKey: '',
        geminiKey: '',
        opencodeKey: '',
        openrouterKey: '',
      },
      updateSettings: () => {},
    }),
  };
});

import {HomeScreen} from '../HomeScreen';
import {AppContext} from '../../../App';
import type {AppSettings} from '../../types';

const mockStatusListeners = new Set<(status: 'connecting' | 'connected' | 'disconnected' | 'error') => void>();
const mockQuestionListeners = new Set<(message: {id: string; message: string; options: string[]; request_id?: string}) => void>();

jest.mock('../../components/ConnectionStatus', () => {
  const ReactLocal = require('react');
  return {
    ConnectionStatus: (props: unknown) => ReactLocal.createElement('ConnectionStatusMock', props),
  };
});

jest.mock('../../components/RecordButton', () => {
  const ReactLocal = require('react');
  return {
    RecordButton: (props: unknown) => ReactLocal.createElement('RecordButtonMock', props),
  };
});

jest.mock('../../components/CommandLog', () => {
  const ReactLocal = require('react');
  return {
    CommandLog: (props: unknown) => ReactLocal.createElement('CommandLogMock', props),
  };
});

jest.mock('../../components/ConversationThread', () => {
  const ReactLocal = require('react');
  return {
    ConversationThread: (props: unknown) => ReactLocal.createElement('ConversationThreadMock', props),
  };
});

jest.mock('../../components/ClarificationDialog', () => {
  const ReactLocal = require('react');
  return {
    ClarificationDialog: (props: unknown) => ReactLocal.createElement('ClarificationDialogMock', props),
  };
});

const mockConversationMode = {
  isActive: false,
  messages: [],
  liveText: '',
  start: jest.fn(async () => {}),
  stop: jest.fn(async () => {}),
  resetSession: jest.fn(async () => {}),
  handleStreamChunk: jest.fn(),
  handleStreamResult: jest.fn(),
  handleStreamQuestion: jest.fn(),
};

jest.mock('../../hooks/useConversationMode', () => ({
  useConversationMode: () => mockConversationMode,
}));

jest.mock('../../services/websocket', () => ({
  wsService: {
    onStatusChange: jest.fn((callback: (status: 'connecting' | 'connected' | 'disconnected' | 'error') => void) => {
      mockStatusListeners.add(callback);
      return () => mockStatusListeners.delete(callback);
    }),
    onQuestion: jest.fn((callback: (message: {id: string; message: string; options: string[]; request_id?: string}) => void) => {
      mockQuestionListeners.add(callback);
      return () => mockQuestionListeners.delete(callback);
    }),
    onStreamChunk: jest.fn(() => () => {}),
    onStreamResult: jest.fn(() => () => {}),
    onResult: jest.fn(() => () => {}),
    connect: jest.fn(() => {
      mockStatusListeners.forEach(callback => callback('connected'));
    }),
    disconnect: jest.fn(),
    sendWithSession: jest.fn(() => ({ok: true})),
    sendAnswer: jest.fn(() => ({ok: true})),
  },
}));

const {wsService: mockWsService} = jest.requireMock('../../services/websocket') as {
  wsService: {
    sendWithSession: jest.Mock;
    sendAnswer: jest.Mock;
    disconnect: jest.Mock;
    connect: jest.Mock;
  };
};

const defaultSettings: AppSettings = {
  serverUrl: 'ws://192.168.1.10:8765',
  openaiKey: 'test-key',
  geminiKey: '',
  opencodeKey: '',
  openrouterKey: '',
};

function renderHome(settings: AppSettings = defaultSettings) {
  return TestRenderer.create(
    <AppContext.Provider value={{settings, updateSettings: jest.fn()}}>
      <HomeScreen />
    </AppContext.Provider>,
  );
}

function emitQuestion(message: {id: string; message: string; options: string[]; request_id?: string}) {
  mockQuestionListeners.forEach(callback => callback(message));
}

describe('HomeScreen', () => {
  let renderer: TestRenderer.ReactTestRenderer | null = null;

  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    mockStatusListeners.clear();
    mockQuestionListeners.clear();
    mockConversationMode.isActive = false;
    mockConversationMode.messages = [];
    mockConversationMode.liveText = '';
    jest.spyOn(Animated, 'timing').mockReturnValue({
      start: (callback?: (result?: {finished: boolean}) => void) => callback?.({finished: true}),
      stop: jest.fn(),
      reset: jest.fn(),
    } as never);
    jest.spyOn(Animated, 'sequence').mockReturnValue({
      start: (callback?: (result?: {finished: boolean}) => void) => callback?.({finished: true}),
      stop: jest.fn(),
      reset: jest.fn(),
    } as never);
  });

  afterEach(() => {
    if (renderer) {
      act(() => {
        renderer?.unmount();
      });
      renderer = null;
    }
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  test('shows voice send failures in the command log', async () => {
    mockWsService.sendWithSession.mockReturnValueOnce({
      ok: false,
      error: 'Not connected to server.',
    });

    renderer = renderHome();

    await act(async () => {
      await Promise.resolve();
    });

    const recordButton = renderer.root.find(
      node => String(node.type) === 'RecordButtonMock',
    );

    await act(async () => {
      recordButton.props.onTranscript('open notepad');
      await Promise.resolve();
    });

    const commandLog = renderer.root.find(
      node => String(node.type) === 'CommandLogMock',
    );
    expect(commandLog.props.entries).toHaveLength(1);
    expect(commandLog.props.entries[0]).toMatchObject({
      transcript: 'open notepad',
      result: 'Not connected to server.',
      success: false,
    });
  });

  test('sends chat clarification answers with the matching request id', async () => {
    renderer = renderHome();

    await act(async () => {
      await Promise.resolve();
    });

    const chatToggle = renderer.root.find(
      node => node.props.accessibilityLabel === 'Switch to chat mode',
    );

    await act(async () => {
      await chatToggle.props.onPress();
    });

    act(() => {
      emitQuestion({
        id: 'question-1',
        message: 'Which one?',
        options: ['Option A'],
        request_id: 'req_q1',
      });
    });

    const input = renderer.root.findByType(TextInput);
    act(() => {
      input.props.onChangeText('option a');
    });

    const sendButton = renderer.root.find(
      node => node.props.accessibilityLabel === 'Send clarification answer',
    );

    act(() => {
      sendButton.props.onPress();
    });

    expect(mockWsService.sendAnswer).toHaveBeenCalledWith(
      'question-1',
      'option a',
      'req_q1',
    );
  });

  test('keeps the clarification dialog open when sending an answer fails', async () => {
    mockWsService.sendAnswer.mockReturnValueOnce({
      ok: false,
      error: 'Not connected to server.',
    });

    renderer = renderHome();

    await act(async () => {
      await Promise.resolve();
    });

    const chatToggle = renderer.root.find(
      node => node.props.accessibilityLabel === 'Switch to chat mode',
    );

    await act(async () => {
      await chatToggle.props.onPress();
    });

    act(() => {
      emitQuestion({
        id: 'question-1',
        message: 'Which one?',
        options: ['Option A'],
        request_id: 'req_q1',
      });
    });

    const input = renderer.root.findByType(TextInput);
    act(() => {
      input.props.onChangeText('option a');
    });

    const sendButton = renderer.root.find(
      node => node.props.accessibilityLabel === 'Send clarification answer',
    );

    act(() => {
      sendButton.props.onPress();
    });

    expect(mockWsService.sendAnswer).toHaveBeenCalledWith(
      'question-1',
      'option a',
      'req_q1',
    );

    const clarificationInput = renderer.root.find(
      node => node.props.accessibilityLabel === 'Type your clarification answer',
    );

    expect(clarificationInput).toBeTruthy();
  });
});
