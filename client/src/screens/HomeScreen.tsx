import React, {useState, useEffect, useCallback, useContext, useRef} from 'react';
import {
  View,
  Text,
  TextInput,
  StyleSheet,
  SafeAreaView,
  TouchableOpacity,
  Animated,
  KeyboardAvoidingView,
  Platform,
} from 'react-native';
import {ConnectionStatus} from '../components/ConnectionStatus';
import {RecordButton, RecordingState} from '../components/RecordButton';
import {CommandLog} from '../components/CommandLog';
import {ConversationThread} from '../components/ConversationThread';
import {ClarificationDialog} from '../components/ClarificationDialog';
import {wsService} from '../services/websocket';
import {AppContext} from '../../App';
import {
  CommandLogEntry,
  ConnectionStatus as ConnectionStatusType,
  ConversationMessage,
  getActiveProvider,
} from '../types';
import {useConversationMode} from '../hooks/useConversationMode';

type PipelineStep = 'idle' | 'listening' | 'processing_stt' | 'sending' | 'waiting' | 'done' | 'error';
type AppMode = 'voice' | 'conversation' | 'chat';

const MAX_LOG = 10;
const SESSION_TIMEOUT_MS = 5 * 60 * 1000;

function limitEntries(entries: CommandLogEntry[]): CommandLogEntry[] {
  return entries.slice(0, MAX_LOG);
}

function getStatusBar(step: PipelineStep, hearingText: string, lastResult: string): {text: string; color: string} {
  switch (step) {
    case 'idle':
      return {text: 'Hold the mic button to speak', color: '#94A3B8'};
    case 'listening':
      return {text: hearingText || 'Listening...', color: '#DC2626'};
    case 'processing_stt':
      return {text: hearingText || 'Processing speech...', color: '#F59E0B'};
    case 'sending':
      return {text: 'Sending to server...', color: '#F59E0B'};
    case 'waiting':
      return {text: 'Waiting for AI response...', color: '#8B5CF6'};
    case 'done':
      return {text: lastResult, color: '#22C55E'};
    case 'error':
      return {text: lastResult, color: '#DC2626'};
  }
}

let sessionCounter = 0;

export const HomeScreen: React.FC = () => {
  const {settings} = useContext(AppContext);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatusType>('disconnected');
  const [logEntries, setLogEntries] = useState<CommandLogEntry[]>([]);
  const [question, setQuestion] = useState<{
    id: string;
    message: string;
    options: string[];
  } | null>(null);
  const [pipelineStep, setPipelineStep] = useState<PipelineStep>('idle');
  const [hearingText, setHearingText] = useState('');
  const [lastResult, setLastResult] = useState('');
  const doneTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const statusAnim = useRef(new Animated.Value(1)).current;

  const sessionIdRef = useRef(`chat_${Date.now()}_${++sessionCounter}`);
  const sessionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const convMode = useConversationMode();
  const [appMode, setAppMode] = useState<AppMode>('voice');
  const convModeRef = useRef(false);
  const chatModeRef = useRef(false);

  // Chat mode state
  const [chatMessages, setChatMessages] = useState<ConversationMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatWaiting, setChatWaiting] = useState(false);
  const chatInputRef = useRef<TextInput>(null);

  const resetSession = useCallback(() => {
    sessionIdRef.current = `chat_${Date.now()}_${++sessionCounter}`;
    if (sessionTimerRef.current) clearTimeout(sessionTimerRef.current);
    setLogEntries([]);
    setLastResult('');
    setPipelineStep('idle');
    setChatMessages([]);
    setChatWaiting(false);
  }, []);

  const refreshSessionTimer = useCallback(() => {
    if (sessionTimerRef.current) clearTimeout(sessionTimerRef.current);
    sessionTimerRef.current = setTimeout(() => {
      resetSession();
    }, SESSION_TIMEOUT_MS);
  }, [resetSession]);

  useEffect(() => {
    return () => {
      if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
      if (sessionTimerRef.current) clearTimeout(sessionTimerRef.current);
    };
  }, []);

  useEffect(() => {
    resetSession();
  }, [settings.serverUrl, settings.openaiKey, settings.geminiKey, settings.opencodeKey, settings.openrouterKey]);

  useEffect(() => {
    convModeRef.current = appMode === 'conversation';
    chatModeRef.current = appMode === 'chat';
  }, [appMode]);

  useEffect(() => {
    wsService.onStatusChange(setConnectionStatus);
    wsService.onResult(result => {
      if (convModeRef.current) {
        convMode.handleStreamResult(result.message, result.success);
      } else if (chatModeRef.current) {
        setChatMessages(prev => [
          ...prev,
          {
            id: `ai_${Date.now()}`,
            role: 'assistant',
            text: result.message,
            timestamp: Date.now(),
            isFinal: true,
          },
        ]);
        setChatWaiting(false);
      } else {
        setLastResult(result.message);
        if (result.success) {
          setPipelineStep('done');
        } else {
          setPipelineStep('error');
        }
        Animated.sequence([
          Animated.timing(statusAnim, {toValue: 1, duration: 200, useNativeDriver: true}),
        ]).start();
        if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
        doneTimerRef.current = setTimeout(() => setPipelineStep('idle'), 5000);
        setLogEntries(prev => {
          for (let i = 0; i < prev.length; i++) {
            if (prev[i].result === 'Sending...') {
              const updated = [...prev];
              updated[i] = {
                ...updated[i],
                result: result.message,
                success: result.success,
              };
              return limitEntries(updated);
            }
          }
          return limitEntries(prev);
        });
      }
    });
    wsService.onQuestion(q => {
      if (convModeRef.current) {
        convMode.handleStreamQuestion(q.id, `${q.message}\n${q.options.map((o, i) => `${i + 1}. ${o}`).join('\n')}`);
      } else if (chatModeRef.current) {
        setChatMessages(prev => [
          ...prev,
          {
            id: `q_${Date.now()}`,
            role: 'question',
            text: `${q.message}\n${q.options.map((o, i) => `${i + 1}. ${o}`).join('\n')}`,
            timestamp: Date.now(),
            isFinal: true,
          },
        ]);
      } else {
        setQuestion({id: q.id, message: q.message, options: q.options});
      }
    });

    const {apiKey, provider} = getActiveProvider(settings);
    if (settings.serverUrl && apiKey) {
      wsService.connect(settings.serverUrl, apiKey, provider);
    }

    return () => {
      wsService.disconnect();
    };
  }, [settings.serverUrl, settings.openaiKey, settings.geminiKey, settings.opencodeKey, settings.openrouterKey]);

  const switchMode = useCallback(async (newMode: AppMode) => {
    if (appMode === 'conversation') {
      await convMode.stop();
    }
    setAppMode(newMode);
  }, [appMode, convMode]);

  const handleTranscript = useCallback((text: string) => {
    if (question) {
      return;
    }
    setPipelineStep('sending');
    refreshSessionTimer();
    const entry: CommandLogEntry = {
      id: Date.now().toString(),
      transcript: text,
      result: 'Sending...',
      success: true,
      timestamp: Date.now(),
    };
    setLogEntries(prev => limitEntries([entry, ...prev]));
    wsService.sendWithSession(text, sessionIdRef.current);
    setTimeout(() => setPipelineStep('waiting'), 500);
  }, [question, refreshSessionTimer]);

  const handleRecordingState = useCallback((state: RecordingState) => {
    if (state === 'listening') {
      setPipelineStep('listening');
    } else if (state === 'processing_stt') {
      setPipelineStep('processing_stt');
    } else if (state === 'idle') {
      if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
      doneTimerRef.current = setTimeout(() => setPipelineStep('idle'), 3000);
    }
  }, []);

  const handleHearingChange = useCallback((text: string) => {
    setHearingText(text);
  }, []);

  const handleSttError = useCallback((error: string) => {
    setLastResult(error);
    setPipelineStep('error');
    if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
    doneTimerRef.current = setTimeout(() => setPipelineStep('idle'), 5000);
    const entry: CommandLogEntry = {
      id: Date.now().toString(),
      transcript: '',
      result: `STT Error: ${error}`,
      success: false,
      timestamp: Date.now(),
    };
    setLogEntries(prev => limitEntries([entry, ...prev]));
  }, []);

  const handleAnswer = useCallback((text: string) => {
    if (question) {
      wsService.sendAnswer(question.id, text);
      setQuestion(null);
    }
  }, [question]);

  // Chat mode: send text message
  const handleChatSend = useCallback(() => {
    const text = chatInput.trim();
    if (!text || chatWaiting) return;

    refreshSessionTimer();
    setChatMessages(prev => [
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: 'user',
        text,
        timestamp: Date.now(),
        isFinal: true,
      },
    ]);
    setChatInput('');
    setChatWaiting(true);
    wsService.sendWithSession(text, sessionIdRef.current);
  }, [chatInput, chatWaiting, refreshSessionTimer]);

  // Conversation mode callbacks
  const toggleConversationMode = useCallback(async () => {
    if (appMode === 'conversation') {
      await switchMode('voice');
    } else {
      await switchMode('conversation');
      await convMode.start();
    }
  }, [appMode, switchMode, convMode]);

  const toggleChatMode = useCallback(() => {
    if (appMode === 'chat') {
      switchMode('voice');
    } else {
      switchMode('chat');
    }
  }, [appMode, switchMode]);

  // ─── Conversation Mode View ─────────────────────────────────
  if (appMode === 'conversation') {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.convTopBar}>
          <ConnectionStatus
            status={connectionStatus}
            serverUrl={settings.serverUrl}
            compact
          />
          <View style={styles.convTopRight}>
            <TouchableOpacity onPress={resetSession} style={styles.convNewChatBtn}>
              <Text style={styles.convNewChatText}>New Chat</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => switchMode('voice')} style={styles.endButton}>
              <Text style={styles.endButtonText}>End</Text>
            </TouchableOpacity>
          </View>
        </View>
        <ConversationThread
          messages={convMode.messages}
          liveText={convMode.liveText}
          isListening={convMode.isActive}
        />
        <View style={styles.convListeningBar}>
          <Animated.View style={[styles.listeningDot, convMode.isActive && styles.listeningDotActive]} />
          <Text style={styles.listeningText}>
            {convMode.isActive ? 'Listening...' : 'Stopped'}
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  // ─── Chat Mode View ─────────────────────────────────────────
  if (appMode === 'chat') {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.convTopBar}>
          <ConnectionStatus
            status={connectionStatus}
            serverUrl={settings.serverUrl}
            compact
          />
          <View style={styles.convTopRight}>
            <TouchableOpacity onPress={resetSession} style={styles.convNewChatBtn}>
              <Text style={styles.convNewChatText}>New Chat</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={() => switchMode('voice')} style={styles.endButton}>
              <Text style={styles.endButtonText}>Voice</Text>
            </TouchableOpacity>
          </View>
        </View>
        <ConversationThread
          messages={chatMessages}
          liveText={undefined}
          isListening={false}
        />
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          keyboardVerticalOffset={0}>
          <View style={styles.chatInputBar}>
            <TextInput
              ref={chatInputRef}
              style={styles.chatInput}
              value={chatInput}
              onChangeText={setChatInput}
              placeholder="Type a command..."
              placeholderTextColor="#94A3B8"
              multiline
              maxLength={500}
              editable={!chatWaiting}
            />
            <TouchableOpacity
              style={[styles.chatSendBtn, (!chatInput.trim() || chatWaiting) && styles.chatSendBtnDisabled]}
              onPress={handleChatSend}
              disabled={!chatInput.trim() || chatWaiting}>
              <Text style={styles.chatSendBtnText}>{chatWaiting ? '...' : 'Send'}</Text>
            </TouchableOpacity>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    );
  }

  // ─── Voice Mode View (default) ──────────────────────────────
  const sb = getStatusBar(pipelineStep, hearingText, lastResult);

  return (
    <SafeAreaView style={styles.container}>
      <ConnectionStatus
        status={connectionStatus}
        serverUrl={settings.serverUrl}
      />
      <View style={styles.content}>
        <View style={styles.topActions}>
          <TouchableOpacity
            onPress={toggleConversationMode}
            style={[styles.conversationToggle, connectionStatus !== 'connected' && styles.conversationToggleDisabled]}
            disabled={connectionStatus !== 'connected'}
          >
            <Text style={[styles.conversationToggleText, connectionStatus !== 'connected' && styles.conversationToggleTextDisabled]}>
              Conversation
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={toggleChatMode}
            style={[styles.chatToggle, connectionStatus !== 'connected' && styles.conversationToggleDisabled]}
            disabled={connectionStatus !== 'connected'}
          >
            <Text style={[styles.chatToggleText, connectionStatus !== 'connected' && styles.conversationToggleTextDisabled]}>
              Chat
            </Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={resetSession} style={styles.newChatBtn}>
            <Text style={styles.newChatBtnText}>New Chat</Text>
          </TouchableOpacity>
        </View>
        <RecordButton
          onTranscript={handleTranscript}
          onSttError={handleSttError}
          onRecordingState={handleRecordingState}
          onHearingChange={handleHearingChange}
          disabled={connectionStatus !== 'connected' || question !== null}
        />
        <Animated.View style={[styles.statusBar, {backgroundColor: sb.color + '12', opacity: statusAnim}]}>
          <Text style={[styles.statusText, {color: sb.color}]}>
            {sb.text}
          </Text>
        </Animated.View>
      </View>
      <CommandLog entries={logEntries} />
      <ClarificationDialog
        visible={question !== null}
        question={question?.message ?? ''}
        options={question?.options ?? []}
        onAnswer={handleAnswer}
        onDismiss={() => setQuestion(null)}
      />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    paddingVertical: 16,
  },
  topActions: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 20,
    gap: 8,
  },
  conversationToggle: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    backgroundColor: '#F1F5F9',
    borderRadius: 20,
  },
  conversationToggleText: {
    fontSize: 13,
    color: '#475569',
    fontWeight: '600',
  },
  conversationToggleDisabled: {
    backgroundColor: '#F8FAFC',
  },
  conversationToggleTextDisabled: {
    color: '#CBD5E1',
  },
  chatToggle: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    backgroundColor: '#EFF6FF',
    borderRadius: 20,
  },
  chatToggleText: {
    fontSize: 13,
    color: '#2563EB',
    fontWeight: '600',
  },
  newChatBtn: {
    paddingVertical: 8,
    paddingHorizontal: 14,
    backgroundColor: '#F0FDF4',
    borderRadius: 20,
  },
  newChatBtnText: {
    fontSize: 13,
    color: '#22C55E',
    fontWeight: '600',
  },
  statusBar: {
    marginTop: 16,
    marginHorizontal: 24,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 12,
  },
  statusText: {
    fontSize: 13,
    fontWeight: '500',
    textAlign: 'center',
  },
  convTopBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#E2E8F0',
  },
  convTopRight: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  convNewChatBtn: {
    paddingVertical: 6,
    paddingHorizontal: 12,
    backgroundColor: '#EFF6FF',
    borderRadius: 14,
  },
  convNewChatText: {
    color: '#2563EB',
    fontSize: 12,
    fontWeight: '600',
  },
  endButton: {
    paddingVertical: 6,
    paddingHorizontal: 14,
    backgroundColor: '#FEE2E2',
    borderRadius: 14,
  },
  endButtonText: {
    color: '#DC2626',
    fontSize: 12,
    fontWeight: '700',
  },
  convListeningBar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 14,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#E2E8F0',
  },
  listeningDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#CBD5E1',
    marginRight: 8,
  },
  listeningDotActive: {
    backgroundColor: '#DC2626',
  },
  listeningText: {
    fontSize: 13,
    color: '#94A3B8',
  },
  // Chat mode styles
  chatInputBar: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#E2E8F0',
    backgroundColor: '#FFFFFF',
  },
  chatInput: {
    flex: 1,
    minHeight: 40,
    maxHeight: 100,
    backgroundColor: '#F1F5F9',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 10,
    fontSize: 14,
    color: '#1E293B',
    marginRight: 8,
  },
  chatSendBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#2563EB',
    justifyContent: 'center',
    alignItems: 'center',
  },
  chatSendBtnDisabled: {
    backgroundColor: '#CBD5E1',
  },
  chatSendBtnText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '700',
  },
});
