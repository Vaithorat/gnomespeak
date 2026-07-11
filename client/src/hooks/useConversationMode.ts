import {useState, useRef, useCallback, useEffect} from 'react';
import Voice, {
  SpeechResultsEvent,
  SpeechErrorEvent,
  SpeechStartEvent,
  SpeechEndEvent,
} from '@react-native-voice/voice';
import {ConversationMessage} from '../types';
import {wsService} from '../services/websocket';

const SILENCE_THRESHOLD_MS = 1500;
const RESTART_DELAY_MS = 300;
const MAX_MESSAGES = 100;
let msgCounter = 0;

let sessionCounter = 0;

function generateSessionId(): string {
  sessionCounter++;
  return `conv_${Date.now()}_${sessionCounter}`;
}

export function useConversationMode() {
  const [isActive, setIsActive] = useState(false);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [liveText, setLiveText] = useState('');

  const transcriptRef = useRef('');
  const sessionIdRef = useRef('');
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const isListeningRef = useRef(false);
  const pendingQuestionRef = useRef<{id: string} | null>(null);
  const isActiveRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      cleanupVoice();
    };
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
  }, []);

  const clearSilenceTimer = () => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  };

  const sendTranscript = useCallback((text: string) => {
    if (!text.trim()) return;
    const msg: ConversationMessage = {
      id: `user_${Date.now()}_${++msgCounter}`,
      role: 'user',
      text: text.trim(),
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev.slice(-MAX_MESSAGES + 1), msg]);

    if (pendingQuestionRef.current) {
      wsService.sendAnswer(pendingQuestionRef.current.id, text.trim());
      pendingQuestionRef.current = null;
    } else {
      wsService.sendWithSession(text.trim(), sessionIdRef.current);
    }
  }, []);

  const finalizeTranscript = useCallback(() => {
    const text = transcriptRef.current.trim();
    if (text) {
      sendTranscript(text);
      transcriptRef.current = '';
      setLiveText('');
    }
    clearSilenceTimer();
  }, [sendTranscript]);

  const startVoiceEngine = useCallback(async () => {
    transcriptRef.current = '';
    Voice.onSpeechStart = (_e: SpeechStartEvent) => {
      setLiveText('...');
    };
    Voice.onSpeechEnd = (_e: SpeechEndEvent) => {};
    Voice.onSpeechResults = (e: SpeechResultsEvent) => {
      if (e.value?.[0]) {
        transcriptRef.current = e.value[0];
        setLiveText(e.value[0]);
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
        setTimeout(() => startVoiceEngine(), 500);
      }
    };
    await Voice.start('en-US');
    isListeningRef.current = true;
  }, [finalizeTranscript, cleanupVoice]);

  const restartListening = useCallback(async () => {
    if (!mountedRef.current) return;
    try {
      await cleanupVoice();
      if (!mountedRef.current) return;
      await new Promise(r => setTimeout(r, RESTART_DELAY_MS));
      if (!mountedRef.current) return;
      await startVoiceEngine();
    } catch {
      try {
        await new Promise(r => setTimeout(r, 500));
        await startVoiceEngine();
      } catch {
        setIsActive(false);
        isActiveRef.current = false;
      }
    }
  }, [cleanupVoice, startVoiceEngine]);

  const start = useCallback(async () => {
    sessionIdRef.current = generateSessionId();
    setMessages([]);
    setLiveText('');
    pendingQuestionRef.current = null;
    transcriptRef.current = '';
    setIsActive(true);
    isActiveRef.current = true;
    try {
      await startVoiceEngine();
    } catch {
      setIsActive(false);
      isActiveRef.current = false;
    }
  }, [startVoiceEngine]);

  const stop = useCallback(async () => {
    setIsActive(false);
    isActiveRef.current = false;
    isListeningRef.current = false;
    clearSilenceTimer();
    finalizeTranscript();
    await cleanupVoice();
  }, [finalizeTranscript, cleanupVoice]);

  const handleStreamResult = useCallback((message: string, success: boolean) => {
    const msg: ConversationMessage = {
      id: `ai_${Date.now()}_${++msgCounter}`,
      role: 'assistant',
      text: message,
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev.slice(-MAX_MESSAGES + 1), msg]);
    if (isActiveRef.current) {
      restartListening();
    }
  }, [restartListening]);

  const handleStreamQuestion = useCallback((id: string, text: string) => {
    const msg: ConversationMessage = {
      id: `q_${Date.now()}_${++msgCounter}`,
      role: 'question',
      text,
      timestamp: Date.now(),
    };
    setMessages(prev => [...prev.slice(-MAX_MESSAGES + 1), msg]);
    pendingQuestionRef.current = {id};
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
    handleStreamResult,
    handleStreamQuestion,
  };
}
