import {useState, useRef, useCallback, useEffect} from 'react';
import Voice, {
  SpeechResultsEvent,
  SpeechErrorEvent,
  SpeechStartEvent,
  SpeechEndEvent,
} from '@react-native-voice/voice';
import {AppState, AppStateStatus} from 'react-native';
import {ConversationMessage} from '../types';
import {wsService} from '../services/websocket';

const SILENCE_THRESHOLD_MS = 1500;
const RESTART_DELAY_MS = 300;
const MAX_MESSAGES = 100;
type PendingQuestionState = {id: string; requestId?: string};
type RequestState = {text: string; msgId?: string};
let msgCounter = 0;

let sessionCounter = 0;
let requestCounter = 0;

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

function generateSessionId(): string {
  sessionCounter++;
  return `conv_${Date.now()}_${sessionCounter}`;
}

function generateRequestId(): string {
  requestCounter++;
  return `req_${Date.now()}_${requestCounter}`;
}

export function useConversationMode() {
  const [isActive, setIsActive] = useState(false);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [liveText, setLiveText] = useState('');

  const transcriptRef = useRef('');
  const transcriptAlternativesRef = useRef<string[]>([]);
  const sessionIdRef = useRef('');
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const isListeningRef = useRef(false);
  const pendingQuestionsRef = useRef(new Map<string, PendingQuestionState>());
  const activeQuestionRequestIdRef = useRef<string | null>(null);
  const isActiveRef = useRef(false);
  const requestStatesRef = useRef(new Map<string, RequestState>());
  const desiredActiveRef = useRef(false);
  const appStateRef = useRef<AppStateStatus>(AppState.currentState);
  const voiceOperationRef = useRef<Promise<void>>(Promise.resolve());
  const restartPendingRef = useRef(false);
  const restartListeningRef = useRef<() => void>(() => {});

  const runVoiceOperation = useCallback((operation: () => Promise<void>) => {
    const next = voiceOperationRef.current.catch(() => {}).then(operation);
    voiceOperationRef.current = next.catch(() => {});
    return next;
  }, []);

  const cleanupVoice = useCallback(async () => {
    try {
      Voice.onSpeechStart = null as any;
      Voice.onSpeechEnd = null as any;
      Voice.onSpeechResults = null as any;
      Voice.onSpeechError = null as any;
      try { await Voice.stop(); } catch {}
      await Voice.destroy();
    } catch {}
    isListeningRef.current = false;
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      void cleanupVoice();
    };
  }, [cleanupVoice]);

  const cancelLiveTranscript = useCallback(() => {
    transcriptRef.current = '';
    transcriptAlternativesRef.current = [];
    setLiveText('');
    clearSilenceTimer();
  }, []);

  const clearSilenceTimer = () => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  };

  const sendTranscript = useCallback((text: string, alternatives: string[] = []) => {
    if (!text.trim()) return;
    const msg: ConversationMessage = {
      id: `user_${Date.now()}_${++msgCounter}`,
      role: 'user',
      text: text.trim(),
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev.slice(-MAX_MESSAGES + 1), msg]);

    const activeQuestionRequestId = activeQuestionRequestIdRef.current;
    if (activeQuestionRequestId) {
      const pendingQuestion = pendingQuestionsRef.current.get(activeQuestionRequestId);
      if (!pendingQuestion) {
        activeQuestionRequestIdRef.current = null;
        return;
      }
      const sendStatus = wsService.sendAnswer(
        pendingQuestion.id,
        text.trim(),
        pendingQuestion.requestId,
      );
      if (!sendStatus.ok) {
        const errorMsg: ConversationMessage = {
          id: `ai_${Date.now()}_${++msgCounter}`,
          role: 'assistant',
          text: sendStatus.error || 'Failed to send answer.',
          timestamp: Date.now(),
        };
        setMessages(prev => [...prev.slice(-MAX_MESSAGES + 1), errorMsg]);
        return;
      }
      pendingQuestionsRef.current.delete(activeQuestionRequestId);
      activeQuestionRequestIdRef.current = null;
    } else {
      const requestId = generateRequestId();
      requestStatesRef.current.set(requestId, {text: ''});
      const sendStatus = wsService.sendWithSession(text.trim(), sessionIdRef.current, requestId, alternatives);
      if (!sendStatus.ok) {
        requestStatesRef.current.delete(requestId);
        const errorMsg: ConversationMessage = {
          id: `ai_${Date.now()}_${++msgCounter}`,
          role: 'assistant',
          text: sendStatus.error || 'Failed to send message.',
          timestamp: Date.now(),
        };
        setMessages(prev => [...prev.slice(-MAX_MESSAGES + 1), errorMsg]);
      }
    }
  }, []);

  const finalizeTranscript = useCallback(() => {
    const text = transcriptRef.current.trim();
    if (text) {
      sendTranscript(text, transcriptAlternativesRef.current);
      transcriptRef.current = '';
      transcriptAlternativesRef.current = [];
      setLiveText('');
    }
    clearSilenceTimer();
  }, [sendTranscript]);

  const startVoiceEngine = useCallback(async () => {
    if (
      !mountedRef.current ||
      !desiredActiveRef.current ||
      isListeningRef.current ||
      appStateRef.current !== 'active'
    ) {
      return;
    }
    transcriptRef.current = '';
    Voice.onSpeechStart = (_e: SpeechStartEvent) => {
      setLiveText('...');
    };
    Voice.onSpeechEnd = (_e: SpeechEndEvent) => {};
    Voice.onSpeechResults = (e: SpeechResultsEvent) => {
        if (e.value?.[0]) {
          const alternatives = normalizeAlternatives(e.value);
          transcriptAlternativesRef.current = alternatives;
          transcriptRef.current = alternatives[0] || '';
          setLiveText(transcriptRef.current);
        }
      clearSilenceTimer();
      silenceTimerRef.current = setTimeout(() => {
        finalizeTranscript();
      }, SILENCE_THRESHOLD_MS);
    };
    Voice.onSpeechError = async (e: SpeechErrorEvent) => {
      const code = e.error?.code;
      if (code === '5' || code === '6') return;
      await cleanupVoice();
      if (isListeningRef.current) {
        return;
      }
      if (desiredActiveRef.current) {
        restartListeningRef.current();
      }
    };
    await Voice.start(getSpeechLocale());
    isListeningRef.current = true;
  }, [cleanupVoice, finalizeTranscript]);

  const restartListening = useCallback(async () => {
    if (!mountedRef.current || !desiredActiveRef.current || restartPendingRef.current) return;
    restartPendingRef.current = true;
    try {
      await runVoiceOperation(async () => {
        try {
          await cleanupVoice();
          if (!mountedRef.current || !desiredActiveRef.current || appStateRef.current !== 'active') {
            return;
          }
          await new Promise<void>(resolve => setTimeout(resolve, RESTART_DELAY_MS));
          await startVoiceEngine();
        } catch {
          await new Promise<void>(resolve => setTimeout(resolve, 500));
          await startVoiceEngine();
        }
      });
    } catch {
      setIsActive(false);
      isActiveRef.current = false;
      desiredActiveRef.current = false;
    } finally {
      restartPendingRef.current = false;
    }
  }, [cleanupVoice, runVoiceOperation, startVoiceEngine]);

  useEffect(() => {
    restartListeningRef.current = () => {
      void restartListening();
    };
  }, [restartListening]);

  const start = useCallback(async () => {
    sessionIdRef.current = generateSessionId();
    setMessages([]);
    setLiveText('');
    pendingQuestionsRef.current.clear();
    activeQuestionRequestIdRef.current = null;
    transcriptRef.current = '';
    transcriptAlternativesRef.current = [];
    requestStatesRef.current.clear();
    desiredActiveRef.current = true;
    setIsActive(true);
    isActiveRef.current = true;
    try {
      await runVoiceOperation(startVoiceEngine);
    } catch {
      setIsActive(false);
      isActiveRef.current = false;
      desiredActiveRef.current = false;
    }
  }, [runVoiceOperation, startVoiceEngine]);

  const stop = useCallback(async () => {
    desiredActiveRef.current = false;
    setIsActive(false);
    isActiveRef.current = false;
    finalizeTranscript();
    await runVoiceOperation(cleanupVoice);
  }, [cleanupVoice, finalizeTranscript, runVoiceOperation]);

  const resetSession = useCallback(async () => {
    sessionIdRef.current = generateSessionId();
    pendingQuestionsRef.current.clear();
    activeQuestionRequestIdRef.current = null;
    requestStatesRef.current.clear();
    transcriptRef.current = '';
    transcriptAlternativesRef.current = [];
    setMessages([]);
    setLiveText('');
    clearSilenceTimer();

    await runVoiceOperation(async () => {
      await cleanupVoice();
      if (!desiredActiveRef.current || appStateRef.current !== 'active') {
        return;
      }
      await startVoiceEngine();
    });
  }, [cleanupVoice, runVoiceOperation, startVoiceEngine]);

  useEffect(() => {
    const sub = AppState.addEventListener('change', nextState => {
      const wasActive = appStateRef.current === 'active';
      appStateRef.current = nextState;
      if (nextState === 'active') {
        if (desiredActiveRef.current) {
          void restartListening();
        }
        return;
      }
      if (wasActive) {
        cancelLiveTranscript();
        void runVoiceOperation(cleanupVoice);
      }
    });
    return () => sub.remove();
  }, [cancelLiveTranscript, cleanupVoice, restartListening, runVoiceOperation]);

  const handleStreamChunk = useCallback((content: string, requestId?: string) => {
    if (!requestId) {
      return;
    }
    const requestState = requestStatesRef.current.get(requestId);
    if (!requestState) {
      return;
    }
    requestState.text += content;
    const currentText = requestState.text;
    const msgId = requestState.msgId;

    if (msgId) {
      setMessages(prev => {
        const updated = [...prev];
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].id === msgId) {
            updated[i] = {...updated[i], text: currentText};
            break;
          }
        }
        return updated;
      });
    } else {
      const newId = `ai_${Date.now()}_${++msgCounter}`;
      requestState.msgId = newId;
      const msg: ConversationMessage = {
        id: newId,
        role: 'assistant',
        text: currentText,
        timestamp: Date.now(),
      };
      setMessages(prev => [...prev.slice(-MAX_MESSAGES + 1), msg]);
    }
  }, []);

  const handleStreamResult = useCallback((_message: string, success: boolean, requestId?: string) => {
    transcriptRef.current = '';
    setLiveText('');
    clearSilenceTimer();

    const requestState = requestId
      ? requestStatesRef.current.get(requestId)
      : undefined;
    if (requestId) {
      requestStatesRef.current.delete(requestId);
    }
    const finalText = requestState?.text || _message || (success ? 'Done.' : 'Request failed.');
    const msgId = requestState?.msgId;

    if (msgId) {
      setMessages(prev => {
        const updated = [...prev];
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].id === msgId) {
            updated[i] = {...updated[i], text: finalText};
            break;
          }
        }
        return updated;
      });
    } else if (finalText) {
      const msg: ConversationMessage = {
        id: `ai_${Date.now()}_${++msgCounter}`,
        role: 'assistant',
        text: finalText,
        timestamp: Date.now(),
      };
      setMessages(prev => [...prev.slice(-MAX_MESSAGES + 1), msg]);
    }

    if (isActiveRef.current) {
      restartListening();
    }
  }, [restartListening]);

  const handleStreamQuestion = useCallback((id: string, text: string, requestId?: string) => {
    if (!requestId) {
      return;
    }
    const msg: ConversationMessage = {
      id: `q_${Date.now()}_${++msgCounter}`,
      role: 'question',
      text,
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev.slice(-MAX_MESSAGES + 1), msg]);
    pendingQuestionsRef.current.set(requestId, {id, requestId});
    activeQuestionRequestIdRef.current = requestId;
    if (isActiveRef.current) {
      restartListening();
    }
  }, [restartListening]);

  return {
    isActive,
    messages,
    liveText,
    start,
    stop,
    resetSession,
    handleStreamChunk,
    handleStreamResult,
    handleStreamQuestion,
  };
}
