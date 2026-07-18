import React from 'react';
import TestRenderer, {act} from 'react-test-renderer';
import {
  Alert,
  Animated,
  AppState,
  PermissionsAndroid,
} from 'react-native';

import {RecordButton} from '../RecordButton';

jest.mock('@react-native-voice/voice', () => ({
  __esModule: true,
  default: {
    isAvailable: jest.fn().mockResolvedValue(true),
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
  isAvailable: jest.Mock;
  start: jest.Mock;
  stop: jest.Mock;
  destroy: jest.Mock;
  onSpeechStart: ((event: unknown) => void) | null;
  onSpeechEnd: ((event: unknown) => void) | null;
  onSpeechResults: ((event: {value?: string[]}) => void) | null;
  onSpeechError: ((event: unknown) => void) | null;
};

describe('RecordButton', () => {
  let renderer: TestRenderer.ReactTestRenderer | null = null;
  let appStateListener: ((state: string) => void) | null = null;

  beforeEach(() => {
    jest.useFakeTimers();
    jest.clearAllMocks();
    appStateListener = null;

    Object.defineProperty(AppState, 'currentState', {
      configurable: true,
      value: 'active',
    });

    jest.spyOn(PermissionsAndroid, 'check').mockResolvedValue(true);
    jest.spyOn(PermissionsAndroid, 'request').mockResolvedValue(
      PermissionsAndroid.RESULTS.GRANTED,
    );
    jest.spyOn(Alert, 'alert').mockImplementation(jest.fn());
    jest.spyOn(AppState, 'addEventListener').mockImplementation(
      ((_type: string, listener: (state: string) => void) => {
        appStateListener = listener;
        return {remove: jest.fn()};
      }) as typeof AppState.addEventListener,
    );
    jest.spyOn(Animated, 'timing').mockReturnValue({
      start: (callback?: (result?: {finished: boolean}) => void) =>
        callback?.({finished: true}),
      stop: jest.fn(),
      reset: jest.fn(),
    } as never);
    jest.spyOn(Animated, 'sequence').mockReturnValue({
      start: (callback?: (result?: {finished: boolean}) => void) =>
        callback?.({finished: true}),
      stop: jest.fn(),
      reset: jest.fn(),
    } as never);
    jest.spyOn(Animated, 'spring').mockReturnValue({
      start: (callback?: (result?: {finished: boolean}) => void) =>
        callback?.({finished: true}),
      stop: jest.fn(),
      reset: jest.fn(),
    } as never);
    jest.spyOn(Animated, 'loop').mockReturnValue({
      start: jest.fn(),
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

  test('cleans up voice when disabled becomes true', async () => {
    renderer = TestRenderer.create(
      <RecordButton disabled={false} onTranscript={jest.fn()} />,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      renderer!.update(
        <RecordButton disabled={true} onTranscript={jest.fn()} />,
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockVoice.stop).toHaveBeenCalled();
    expect(mockVoice.destroy).toHaveBeenCalled();
  });

  test('cleans up voice when the app leaves the active state', async () => {
    renderer = TestRenderer.create(
      <RecordButton disabled={false} onTranscript={jest.fn()} />,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(typeof appStateListener).toBe('function');

    await act(async () => {
      appStateListener?.('background');
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(mockVoice.stop).toHaveBeenCalled();
    expect(mockVoice.destroy).toHaveBeenCalled();
  });
});
