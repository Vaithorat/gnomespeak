import React, {useCallback, useEffect, useRef, useState} from 'react';
import {
  TouchableOpacity,
  View,
  Text,
  StyleSheet,
  ActivityIndicator,
  Alert,
  Linking,
  PermissionsAndroid,
  Animated,
  Easing,
  AppState,
  AppStateStatus,
  Platform,
} from 'react-native';
import Voice, {
  SpeechResultsEvent,
  SpeechErrorEvent,
  SpeechStartEvent,
  SpeechEndEvent,
} from '@react-native-voice/voice';

export type RecordingState = 'idle' | 'listening' | 'processing_stt';

interface Props {
  onTranscript: (text: string, alternatives?: string[]) => void;
  onSttError?: (error: string) => void;
  onRecordingState?: (state: RecordingState) => void;
  onHearingChange?: (text: string) => void;
  disabled: boolean;
}

const RECORD_TIMEOUT_MS = 10000;
const WAIT_RESULTS_MS = 2000;

function getSpeechLocale(): string {
  try {
    const locale = Intl.DateTimeFormat().resolvedOptions().locale;
    if (locale) {
      return locale.replace('_', '-');
    }
  } catch {}
  return 'en-US';
}

function normalizeAlternatives(values?: string[]): string[] {
  if (!values) {
    return [];
  }
  const seen = new Set<string>();
  const alternatives: string[] = [];
  for (const value of values) {
    const normalized = value.trim();
    if (!normalized) {
      continue;
    }
    const key = normalized.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    alternatives.push(normalized);
    if (alternatives.length >= 5) {
      break;
    }
  }
  return alternatives;
}

export const RecordButton: React.FC<Props> = ({onTranscript, onSttError, onRecordingState, onHearingChange, disabled}) => {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const [hearingText, setHearingText] = useState('');
  const transcriptRef = useRef('');
  const transcriptAlternativesRef = useRef<string[]>([]);
  const onTranscriptRef = useRef(onTranscript);
  const onSttErrorRef = useRef(onSttError);
  const onRecordingStateRef = useRef(onRecordingState);
  const onHearingChangeRef = useRef(onHearingChange);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const graceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const stoppedRef = useRef(false);
  const finalizeRef = useRef<(() => void) | null>(null);
  const finalizedRef = useRef(false);
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);
  const disabledRef = useRef(disabled);
  const isRecordingRef = useRef(false);
  const isProcessingRef = useRef(false);
  const operationRef = useRef<Promise<void>>(Promise.resolve());
  onTranscriptRef.current = onTranscript;
  onSttErrorRef.current = onSttError;
  onRecordingStateRef.current = onRecordingState;
  onHearingChangeRef.current = onHearingChange;
  disabledRef.current = disabled;

  const setRecording = useCallback((value: boolean) => {
    isRecordingRef.current = value;
    setIsRecording(value);
  }, []);

  const setProcessing = useCallback((value: boolean) => {
    isProcessingRef.current = value;
    setIsProcessing(value);
  }, []);

  const runSerialized = useCallback((operation: () => Promise<void>) => {
    const next = operationRef.current.catch(() => {}).then(operation);
    operationRef.current = next.catch(() => {});
    return next;
  }, []);

  const pulseAnim = useRef(new Animated.Value(1)).current;
  const scaleAnim = useRef(new Animated.Value(1)).current;

  useEffect(() => {
    isRecordingRef.current = isRecording;
  }, [isRecording]);

  useEffect(() => {
    isProcessingRef.current = isProcessing;
  }, [isProcessing]);

  const clearGraceTimer = () => {
    if (graceTimerRef.current) {
      clearTimeout(graceTimerRef.current);
      graceTimerRef.current = null;
    }
  };

  const resetVoiceState = useCallback((hearing = '') => {
    clearTimer();
    clearGraceTimer();
    finalizeRef.current = null;
    finalizedRef.current = false;
    stoppedRef.current = true;
    transcriptRef.current = '';
    transcriptAlternativesRef.current = [];
    setRecording(false);
    setProcessing(false);
    setHearingText(hearing);
  }, [setProcessing, setRecording]);

  const cleanupVoice = useCallback(async (hearing = '') => {
    Voice.onSpeechStart = null as any;
    Voice.onSpeechEnd = null as any;
    Voice.onSpeechResults = null as any;
    Voice.onSpeechError = null as any;
    try {
      await Voice.stop();
    } catch {}
    try {
      await Voice.destroy();
    } catch {}
    if (mountedRef.current) {
      resetVoiceState(hearing);
    }
  }, [resetVoiceState]);

  const refreshPermission = useCallback(async (): Promise<boolean> => {
    if (Platform.OS !== 'android') {
      setHasPermission(true);
      return true;
    }
    const ok = await PermissionsAndroid.check(
      PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
    );
    setHasPermission(ok);
    return ok;
  }, []);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      clearTimer();
      clearGraceTimer();
      void runSerialized(() => cleanupVoice());
    };
  }, [cleanupVoice, runSerialized]);

  useEffect(() => {
    void refreshPermission();
    const sub = AppState.addEventListener('change', nextState => {
      const wasActive = appStateRef.current === 'active';
      appStateRef.current = nextState;
      if (nextState === 'active') {
        void refreshPermission();
        return;
      }
      if (wasActive) {
        void runSerialized(() => cleanupVoice());
      }
    });
    return () => sub.remove();
  }, [cleanupVoice, refreshPermission, runSerialized]);

  useEffect(() => {
    if (disabled) {
      void runSerialized(() => cleanupVoice());
    }
  }, [cleanupVoice, disabled, runSerialized]);

  useEffect(() => {
    if (isRecording) {
      const pulse = Animated.loop(
        Animated.sequence([
          Animated.timing(pulseAnim, {toValue: 1.12, duration: 800, easing: Easing.inOut(Easing.ease), useNativeDriver: true}),
          Animated.timing(pulseAnim, {toValue: 1, duration: 800, easing: Easing.inOut(Easing.ease), useNativeDriver: true}),
        ]),
      );
      pulse.start();
      return () => pulse.stop();
    } else {
      pulseAnim.setValue(1);
    }
  }, [isRecording, pulseAnim]);

  useEffect(() => {
    if (isProcessing) {
      onRecordingStateRef.current?.('processing_stt');
    } else if (isRecording) {
      onRecordingStateRef.current?.('listening');
    } else {
      onRecordingStateRef.current?.('idle');
    }
  }, [isRecording, isProcessing]);

  useEffect(() => {
    onHearingChangeRef.current?.(hearingText);
  }, [hearingText]);

  const clearTimer = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  };

  const onSpeechStart = useCallback((_e: SpeechStartEvent) => {
    setHearingText('...');
  }, []);

  const onSpeechEnd = useCallback((_e: SpeechEndEvent) => {
  }, []);

  const onSpeechResults = useCallback((e: SpeechResultsEvent) => {
    clearTimer();
    if (e.value?.[0]) {
      const alternatives = normalizeAlternatives(e.value);
      transcriptAlternativesRef.current = alternatives;
      transcriptRef.current = alternatives[0] || '';
      setHearingText(transcriptRef.current);
    }
    if (finalizeRef.current) {
      finalizeRef.current();
    }
  }, []);

  const sttErrorMsg = (e: SpeechErrorEvent): string => {
    const code = e.error?.code;
    if (!code) return 'Speech recognition failed';
    const map: Record<string, string> = {
      '1': 'Network timeout',
      '2': 'Network error — check internet',
      '3': 'Audio error',
      '4': 'Server error',
      '5': 'No speech detected — try speaking',
      '6': 'No match — try again clearly',
      '7': 'Recognizer busy',
      '8': 'Insufficient permissions',
      '9': 'Too many requests',
    };
    return map[code] || `Error code ${code}`;
  };

  const onSpeechError = useCallback((e: SpeechErrorEvent) => {
    clearTimer();
    const code = e.error?.code;
    const msg = sttErrorMsg(e);
    console.error('STT Error:', code, msg);
    if (stoppedRef.current || transcriptRef.current) {
      return;
    }
    if (code === '5' || code === '6') {
      return;
    }
    setIsRecording(false);
    onSttErrorRef.current?.(msg);
    if (mountedRef.current) {
      Alert.alert('Voice Recognition', msg);
    }
  }, []);

  const showPermissionAlert = useCallback(() => {
    Alert.alert(
      'Microphone Required',
      'VoiceTalk needs microphone access to work. Please enable it in Settings.',
      [
        {text: 'Cancel', style: 'cancel'},
        {text: 'Open Settings', onPress: () => Linking.openSettings()},
      ],
    );
  }, []);

  const getPermission = useCallback(async (): Promise<boolean> => {
    if (await refreshPermission()) {
      return true;
    }
    if (Platform.OS !== 'android') {
      return true;
    }
    const granted = await PermissionsAndroid.request(
      PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
      {
        title: 'Microphone Permission',
        message: 'VoiceTalk needs access to your microphone to capture voice commands.',
        buttonPositive: 'Grant',
        buttonNegative: 'Deny',
        buttonNeutral: 'Ask Later',
      },
    );
    const ok = granted === PermissionsAndroid.RESULTS.GRANTED;
    setHasPermission(ok);
    return ok;
  }, [refreshPermission]);

  const startRecording = useCallback(async () => {
    if (
      disabledRef.current ||
      isRecordingRef.current ||
      isProcessingRef.current ||
      appStateRef.current !== 'active'
    ) {
      return;
    }
    const perm = await getPermission();
    if (!perm) {
      showPermissionAlert();
      return;
    }
    try {
      const available = await Voice.isAvailable();
      if (!available) {
        Alert.alert(
          'Not Available',
          'Speech recognition is not available on this device. Install Google app or check language settings.',
        );
        return;
      }

      stoppedRef.current = false;
      transcriptRef.current = '';
      transcriptAlternativesRef.current = [];
      finalizedRef.current = false;
      clearGraceTimer();
      setHearingText('');
      Voice.onSpeechStart = onSpeechStart;
      Voice.onSpeechEnd = onSpeechEnd;
      Voice.onSpeechResults = onSpeechResults;
      Voice.onSpeechError = onSpeechError;
      setProcessing(false);
      setRecording(true);
      timeoutRef.current = setTimeout(() => {
        if (mountedRef.current) {
          void runSerialized(() => cleanupVoice('Timed out - no speech detected'));
        }
      }, RECORD_TIMEOUT_MS);
      await Voice.start(getSpeechLocale());
    } catch (e) {
      console.error('Failed to start recording:', e);
      await cleanupVoice('Failed to start microphone');
    }
  }, [cleanupVoice, getPermission, onSpeechEnd, onSpeechError, onSpeechResults, onSpeechStart, runSerialized, setProcessing, setRecording, showPermissionAlert]);

  const finalize = useCallback(async () => {
    if (finalizedRef.current) return;
    finalizedRef.current = true;
    clearGraceTimer();
    finalizeRef.current = null;
    try {
      await Voice.destroy();
    } catch {}
    const text = transcriptRef.current.trim();
    if (text) {
      onTranscriptRef.current(text, transcriptAlternativesRef.current);
      setHearingText(`Sent: "${text}"`);
    } else {
      setHearingText('Nothing heard — try again');
    }
    setRecording(false);
    setProcessing(false);
  }, [setProcessing, setRecording]);

  const stopRecording = useCallback(async () => {
    if (!isRecordingRef.current && !isProcessingRef.current) {
      return;
    }
    clearTimer();
    stoppedRef.current = true;
    try {
      setRecording(false);
      setProcessing(true);
      await Voice.stop();

      finalizeRef.current = finalize;

      graceTimerRef.current = setTimeout(() => {
        void runSerialized(finalize);
      }, WAIT_RESULTS_MS);

      if (transcriptRef.current.trim()) {
        await finalize();
      }
    } catch (e) {
      console.error('Failed to stop recording:', e);
      await cleanupVoice('Failed to stop recording');
    }
  }, [cleanupVoice, finalize, runSerialized, setProcessing, setRecording]);

  const handlePressIn = useCallback(() => {
    Animated.spring(scaleAnim, {toValue: 0.92, useNativeDriver: true, friction: 8}).start();
    void runSerialized(startRecording);
  }, [runSerialized, scaleAnim, startRecording]);

  const handlePressOut = useCallback(() => {
    Animated.spring(scaleAnim, {toValue: 1, useNativeDriver: true, friction: 8}).start();
    void runSerialized(stopRecording);
  }, [runSerialized, scaleAnim, stopRecording]);

  const buttonBg = isRecording ? '#DC2626' : isProcessing ? '#F59E0B' : '#2563EB';
  const disabledBg = '#E2E8F0';

  return (
    <View style={styles.wrapper}>
      <Animated.View style={[{transform: [{scale: Animated.multiply(pulseAnim, scaleAnim)}]}]}>
        <TouchableOpacity
          onPressIn={handlePressIn}
          onPressOut={handlePressOut}
          disabled={disabled || isProcessing || hasPermission === false}
          activeOpacity={0.8}
          style={[
            styles.button,
            {backgroundColor: disabled || isProcessing || hasPermission === false ? disabledBg : buttonBg},
          ]}>
          {isProcessing ? (
            <ActivityIndicator size="large" color="#FFF" />
          ) : (
            <Text style={styles.icon}>{isRecording ? '●' : '🎙'}</Text>
          )}
          <Text style={styles.label}>
            {isProcessing
              ? 'Processing...'
              : isRecording
                ? 'Listening...'
                : hasPermission === false
                  ? 'No Mic Access'
                  : 'Hold to Talk'}
          </Text>
        </TouchableOpacity>
      </Animated.View>
      {hearingText ? (
        <Text style={styles.hearingText}>{hearingText}</Text>
      ) : null}
    </View>
  );
};

const styles = StyleSheet.create({
  wrapper: {
    alignItems: 'center',
  },
  hearingText: {
    marginTop: 14,
    fontSize: 13,
    color: '#94A3B8',
    textAlign: 'center',
    paddingHorizontal: 24,
  },
  button: {
    width: 110,
    height: 110,
    borderRadius: 55,
    justifyContent: 'center',
    alignItems: 'center',
    alignSelf: 'center',
  },
  icon: {
    fontSize: 32,
    color: '#FFF',
  },
  label: {
    color: '#FFF',
    fontSize: 11,
    marginTop: 4,
    fontWeight: '600',
  },
});
