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
  Alert,
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
type PendingRequestState = {
  mode: 'voice' | 'chat';
  text: string;
  logId?: string;
  chatMsgId?: string;
};

const MAX_LOG = 10;
const MAX_CHAT_MESSAGES = 100;
const SESSION_TIMEOUT_MS = 5 * 60 * 1000;

function limitEntries(entries: CommandLogEntry[]): CommandLogEntry[] {
  return entries.slice(0, MAX_LOG);
}

function limitConversationMessages(messages: ConversationMessage[]): ConversationMessage[] {
  return messages.slice(-MAX_CHAT_MESSAGES);
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
let requestCounter = 0;

function generateRequestId(): string {
  requestCounter++;
  return `req_${Date.now()}_${requestCounter}`;
}

export const HomeScreen: React.FC = () => {
  const {settings} = useContext(AppContext);
  const {
    apiKey: activeApiKey,
    provider: activeProvider,
  } = getActiveProvider(settings);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatusType>('disconnected');
  const [logEntries, setLogEntries] = useState<CommandLogEntry[]>([]);
  const [question, setQuestion] = useState<{
    id: string;
    message: string;
    options: string[];
    requestId?: string;
  } | null>(null);
  const [pipelineStep, setPipelineStep] = useState<PipelineStep>('idle');
  const [hearingText, setHearingText] = useState('');
  const [lastResult, setLastResult] = useState('');
  const doneTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const statusAnim = useRef(new Animated.Value(1)).current;

  const sessionIdRef = useRef(`chat_${Date.now()}_${++sessionCounter}`);
  const sessionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const {
    isActive: isConversationActive,
    messages: conversationMessages,
    liveText: conversationLiveText,
    start: startConversationMode,
    stop: stopConversationMode,
    resetSession: resetConversationSession,
    handleStreamChunk: handleConversationStreamChunk,
    handleStreamResult: handleConversationStreamResult,
    handleStreamQuestion: handleConversationStreamQuestion,
  } = useConversationMode();
  const [appMode, setAppMode] = useState<AppMode>('voice');
  const convModeRef = useRef(false);
  const chatModeRef = useRef(false);
  const requestStatesRef = useRef(new Map<string, PendingRequestState>());

  // Chat mode state
  const [chatMessages, setChatMessages] = useState<ConversationMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatWaiting, setChatWaiting] = useState(false);
  const chatInputRef = useRef<TextInput>(null);

  const resetSession = useCallback(() => {
    sessionIdRef.current = `chat_${Date.now()}_${++sessionCounter}`;
    if (sessionTimerRef.current) clearTimeout(sessionTimerRef.current);
    requestStatesRef.current.clear();
    setLogEntries([]);
    setQuestion(null);
    setHearingText('');
    setLastResult('');
    setPipelineStep('idle');
    setChatMessages([]);
    setChatWaiting(false);
  }, []);

  const handleNewChat = useCallback(() => {
    const hasConversationActivity = conversationMessages.length > 0 || conversationLiveText;
    const hasActivity =
      hasConversationActivity ||
      logEntries.length > 0 ||
      chatMessages.length > 0 ||
      chatWaiting ||
      question !== null ||
      requestStatesRef.current.size > 0;

    const resetNow = () => {
      resetSession();
      if (appMode === 'conversation') {
        void resetConversationSession();
      }
    };

    if (!hasActivity) {
      resetNow();
      return;
    }

    Alert.alert(
      'Start new chat?',
      'This clears the current conversation and any pending replies.',
      [
        {text: 'Cancel', style: 'cancel'},
        {text: 'New Chat', style: 'destructive', onPress: resetNow},
      ],
    );
  }, [
    appMode,
    chatMessages.length,
    chatWaiting,
    conversationLiveText,
    conversationMessages.length,
    logEntries.length,
    question,
    resetConversationSession,
    resetSession,
  ]);

  const guidanceMessage = !settings.serverUrl.trim()
    ? 'Add your server URL in Settings to connect to your PC.'
    : !activeApiKey
      ? 'Add at least one provider API key in Settings before sending commands.'
      : connectionStatus !== 'connected'
        ? 'Connect to your trusted LAN server before using voice or chat.'
        : '';

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
  }, [resetSession]);

  useEffect(() => {
    resetSession();
  }, [
    resetSession,
    settings.serverUrl,
    settings.openaiKey,
    settings.geminiKey,
    settings.opencodeKey,
    settings.openrouterKey,
  ]);

  useEffect(() => {
    convModeRef.current = appMode === 'conversation';
    chatModeRef.current = appMode === 'chat';
  }, [appMode]);

  useEffect(() => {
    const offStatus = wsService.onStatusChange(setConnectionStatus);

    const offStreamChunk = wsService.onStreamChunk(chunk => {
      const requestId = chunk.request_id;

      if (convModeRef.current) {
        handleConversationStreamChunk(chunk.content, requestId);
      } else {
        if (!requestId) {
          return;
        }
        const requestState = requestStatesRef.current.get(requestId);
        if (!requestState) {
          return;
        }
        requestState.text += chunk.content;
        const currentText = requestState.text;

        if (requestState.mode === 'chat') {
          const msgId = requestState.chatMsgId;
          if (msgId) {
            setChatMessages(prev => {
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
            const newId = `ai_${Date.now()}`;
            requestState.chatMsgId = newId;
            setChatMessages(prev => limitConversationMessages([
              ...prev,
              {
                id: newId,
                role: 'assistant',
                text: currentText,
                timestamp: Date.now(),
                isFinal: false,
              },
            ]));
          }
        } else {
          const logId = requestState.logId;
          if (!logId) {
            return;
          }
          setLogEntries(prev => {
            const updated = [...prev];
            for (let i = 0; i < updated.length; i++) {
              if (updated[i].id === logId) {
                updated[i] = {...updated[i], result: currentText};
                break;
              }
            }
            return updated;
          });
          setLastResult(currentText);
        }
      }
    });

    const offStreamResult = wsService.onStreamResult(result => {
      const requestId = result.request_id;

      if (convModeRef.current) {
        handleConversationStreamResult(result.message, result.success, requestId);
        return;
      }

      const requestState = requestId
        ? requestStatesRef.current.get(requestId)
        : undefined;
      if (requestId) {
        requestStatesRef.current.delete(requestId);
      }
      const finalText = requestState?.text || result.message;

      if (!requestState) {
        if (chatModeRef.current) {
          setChatMessages(prev => limitConversationMessages([
            ...prev,
            {
              id: `ai_${Date.now()}`,
              role: 'assistant',
              text: finalText,
              timestamp: Date.now(),
              isFinal: true,
            },
          ]));
          setChatWaiting(false);
          return;
        }

        setLastResult(finalText);
        setPipelineStep(result.success ? 'done' : 'error');
        Animated.sequence([
          Animated.timing(statusAnim, {toValue: 1, duration: 200, useNativeDriver: true}),
        ]).start();
        if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
        doneTimerRef.current = setTimeout(() => setPipelineStep('idle'), 5000);
        return;
      }

      if (requestState.mode === 'chat') {
        const chatMsgId = requestState.chatMsgId;
        if (chatMsgId) {
          setChatMessages(prev => {
            const updated = [...prev];
            for (let i = updated.length - 1; i >= 0; i--) {
              if (updated[i].id === chatMsgId) {
                updated[i] = {...updated[i], text: finalText, isFinal: true};
                break;
              }
            }
            return updated;
          });
        } else {
          setChatMessages(prev => limitConversationMessages([
            ...prev,
            {
              id: `ai_${Date.now()}`,
              role: 'assistant',
              text: finalText,
              timestamp: Date.now(),
              isFinal: true,
            },
          ]));
        }
        setChatWaiting(false);
      } else {
        const logId = requestState.logId;
        setLastResult(finalText);
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
        if (logId) {
          setLogEntries(prev => {
            const updated = [...prev];
            for (let i = 0; i < updated.length; i++) {
              if (updated[i].id === logId) {
                updated[i] = {...updated[i], result: finalText, success: result.success};
                break;
              }
            }
            return limitEntries(updated);
          });
        }
      }
    });

    const offResult = wsService.onResult(result => {
      if (convModeRef.current) {
        handleConversationStreamResult(result.message, result.success, result.request_id);
      } else {
        const requestState = result.request_id
          ? requestStatesRef.current.get(result.request_id)
          : undefined;
        if (result.request_id) {
          requestStatesRef.current.delete(result.request_id);
        }

        if (!requestState) {
          if (chatModeRef.current) {
            setChatMessages(prev => limitConversationMessages([
              ...prev,
              {
                id: `ai_${Date.now()}`,
                role: 'assistant',
                text: result.message,
                timestamp: Date.now(),
                isFinal: true,
              },
            ]));
            setChatWaiting(false);
            return;
          }

          setLastResult(result.message);
          setPipelineStep(result.success ? 'done' : 'error');
          Animated.sequence([
            Animated.timing(statusAnim, {toValue: 1, duration: 200, useNativeDriver: true}),
          ]).start();
          if (doneTimerRef.current) clearTimeout(doneTimerRef.current);
          doneTimerRef.current = setTimeout(() => setPipelineStep('idle'), 5000);
          return;
        }

        if (requestState.mode === 'chat') {
          setChatMessages(prev => limitConversationMessages([
            ...prev,
            {
              id: `ai_${Date.now()}`,
              role: 'assistant',
              text: result.message,
              timestamp: Date.now(),
              isFinal: true,
            },
          ]));
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
          if (requestState.logId) {
            setLogEntries(prev => limitEntries(prev.map(entry =>
              entry.id === requestState.logId
                ? {...entry, result: result.message, success: result.success}
                : entry,
            )));
          }
        }
      }
    });
    const offQuestion = wsService.onQuestion(q => {
      if (convModeRef.current) {
        handleConversationStreamQuestion(q.id, `${q.message}\n${q.options.map((o, i) => `${i + 1}. ${o}`).join('\n')}`, q.request_id);
      } else {
        if (chatModeRef.current) {
          setChatMessages(prev => limitConversationMessages([
            ...prev,
            {
              id: `q_${Date.now()}`,
              role: 'question',
              text: `${q.message}\n${q.options.map((o, i) => `${i + 1}. ${o}`).join('\n')}`,
              timestamp: Date.now(),
              isFinal: true,
            },
          ]));
        }
        setQuestion({id: q.id, message: q.message, options: q.options, requestId: q.request_id});
      }
    });

    if (settings.serverUrl && activeApiKey) {
      wsService.connect(settings.serverUrl, activeApiKey, activeProvider);
    }

    return () => {
      offStatus();
      offStreamChunk();
      offStreamResult();
      offResult();
      offQuestion();
      wsService.disconnect();
    };
  }, [
    activeApiKey,
    activeProvider,
    handleConversationStreamChunk,
    handleConversationStreamQuestion,
    handleConversationStreamResult,
    settings.serverUrl,
    settings.openaiKey,
    settings.geminiKey,
    settings.opencodeKey,
    settings.openrouterKey,
    statusAnim,
  ]);

  const switchMode = useCallback(async (newMode: AppMode) => {
    if (appMode === 'conversation') {
      await stopConversationMode();
    }
    setAppMode(newMode);
  }, [appMode, stopConversationMode]);

  const handleTranscript = useCallback((text: string, alternatives: string[] = []) => {
    if (question) {
      return;
    }
    setPipelineStep('sending');
    refreshSessionTimer();
    const entryId = Date.now().toString();
    const requestId = generateRequestId();
    requestStatesRef.current.set(requestId, {
      mode: 'voice',
      text: '',
      logId: entryId,
    });
    const entry: CommandLogEntry = {
      id: entryId,
      transcript: text,
      result: 'Sending...',
      success: true,
      timestamp: Date.now(),
    };
    setLogEntries(prev => limitEntries([entry, ...prev]));
    const sendStatus = wsService.sendWithSession(text, sessionIdRef.current, requestId, alternatives);
    if (!sendStatus.ok) {
      requestStatesRef.current.delete(requestId);
      setLastResult(sendStatus.error || 'Failed to send command.');
      setPipelineStep('error');
      setLogEntries(prev => limitEntries(prev.map(entry =>
        entry.id === entryId
          ? {...entry, result: sendStatus.error || 'Failed to send command.', success: false}
          : entry,
      )));
      return;
    }
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
      const sendStatus = wsService.sendAnswer(question.id, text, question.requestId);
      if (!sendStatus.ok) {
        setLastResult(sendStatus.error || 'Failed to send answer.');
        setPipelineStep('error');
        return;
      }
      setQuestion(null);
    }
  }, [question]);

  // Chat mode: send text message
  const handleChatSend = useCallback(() => {
    const text = chatInput.trim();
    if (!text || chatWaiting) return;

    if (question) {
      handleAnswer(text);
      setChatInput('');
      return;
    }

    refreshSessionTimer();
    const requestId = generateRequestId();
    requestStatesRef.current.set(requestId, {
      mode: 'chat',
      text: '',
    });
    setChatMessages(prev => limitConversationMessages([
      ...prev,
      {
        id: `user_${Date.now()}`,
        role: 'user',
        text,
        timestamp: Date.now(),
        isFinal: true,
      },
    ]));
    setChatInput('');
    setChatWaiting(true);
    const sendStatus = wsService.sendWithSession(text, sessionIdRef.current, requestId);
    if (!sendStatus.ok) {
      requestStatesRef.current.delete(requestId);
      setChatWaiting(false);
      setChatMessages(prev => limitConversationMessages([
        ...prev,
        {
          id: `ai_${Date.now()}`,
          role: 'assistant',
          text: sendStatus.error || 'Failed to send message.',
          timestamp: Date.now(),
          isFinal: true,
        },
      ]));
    }
  }, [chatInput, chatWaiting, handleAnswer, question, refreshSessionTimer]);

  // Conversation mode callbacks
  const toggleConversationMode = useCallback(async () => {
    if (appMode === 'conversation') {
      await switchMode('voice');
    } else {
      await switchMode('conversation');
      await startConversationMode();
    }
  }, [appMode, startConversationMode, switchMode]);

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
            <TouchableOpacity
              onPress={handleNewChat}
              style={styles.convNewChatBtn}
              accessibilityRole="button"
              accessibilityLabel="Start a new conversation">
              <Text style={styles.convNewChatText}>New Chat</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => switchMode('voice')}
              style={styles.endButton}
              accessibilityRole="button"
              accessibilityLabel="End conversation mode">
              <Text style={styles.endButtonText}>End</Text>
            </TouchableOpacity>
          </View>
        </View>
        {guidanceMessage ? (
          <View style={styles.guidanceBanner} accessible accessibilityLiveRegion="polite">
            <Text style={styles.guidanceText}>{guidanceMessage}</Text>
          </View>
        ) : null}
        <ConversationThread
          messages={conversationMessages}
          liveText={conversationLiveText}
          isListening={isConversationActive}
        />
        <View style={styles.convListeningBar}>
          <Animated.View style={[styles.listeningDot, isConversationActive && styles.listeningDotActive]} />
          <Text style={styles.listeningText} accessibilityLiveRegion="polite">
            {isConversationActive ? 'Listening...' : 'Stopped'}
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
            <TouchableOpacity
              onPress={handleNewChat}
              style={styles.convNewChatBtn}
              accessibilityRole="button"
              accessibilityLabel="Start a new chat">
              <Text style={styles.convNewChatText}>New Chat</Text>
            </TouchableOpacity>
            <TouchableOpacity
              onPress={() => switchMode('voice')}
              style={styles.endButton}
              accessibilityRole="button"
              accessibilityLabel="Switch to voice mode">
              <Text style={styles.endButtonText}>Voice</Text>
            </TouchableOpacity>
          </View>
        </View>
        {guidanceMessage ? (
          <View style={styles.guidanceBanner} accessible accessibilityLiveRegion="polite">
            <Text style={styles.guidanceText}>{guidanceMessage}</Text>
          </View>
        ) : null}
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
              accessibilityLabel={question ? 'Type your clarification answer' : 'Type a command'}
            />
            <TouchableOpacity
              style={[styles.chatSendBtn, (!chatInput.trim() || chatWaiting) && styles.chatSendBtnDisabled]}
              onPress={handleChatSend}
              disabled={!chatInput.trim() || chatWaiting}
              accessibilityRole="button"
              accessibilityLabel={question ? 'Send clarification answer' : 'Send chat command'}>
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
      {guidanceMessage ? (
        <View style={styles.guidanceBanner} accessible accessibilityLiveRegion="polite">
          <Text style={styles.guidanceText}>{guidanceMessage}</Text>
        </View>
      ) : null}
      <View style={styles.content}>
        <View style={styles.topActions}>
          <TouchableOpacity
            onPress={toggleConversationMode}
            style={[styles.conversationToggle, connectionStatus !== 'connected' && styles.conversationToggleDisabled]}
            disabled={connectionStatus !== 'connected'}
            accessibilityRole="button"
            accessibilityLabel="Switch to conversation mode"
          >
            <Text style={[styles.conversationToggleText, connectionStatus !== 'connected' && styles.conversationToggleTextDisabled]}>
              Conversation
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={toggleChatMode}
            style={[styles.chatToggle, connectionStatus !== 'connected' && styles.conversationToggleDisabled]}
            disabled={connectionStatus !== 'connected'}
            accessibilityRole="button"
            accessibilityLabel="Switch to chat mode"
          >
            <Text style={[styles.chatToggleText, connectionStatus !== 'connected' && styles.conversationToggleTextDisabled]}>
              Chat
            </Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={handleNewChat}
            style={styles.newChatBtn}
            accessibilityRole="button"
            accessibilityLabel="Start a new chat">
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
        <Animated.View
          style={[styles.statusBar, {backgroundColor: sb.color + '12', opacity: statusAnim}]}
          accessible
          accessibilityRole="summary"
          accessibilityState={{busy: pipelineStep === 'sending' || pipelineStep === 'waiting' || pipelineStep === 'processing_stt'}}>
          <Text style={[styles.statusText, {color: sb.color}]} accessibilityLiveRegion="polite">
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
    minHeight: 44,
    paddingVertical: 8,
    paddingHorizontal: 14,
    backgroundColor: '#F1F5F9',
    borderRadius: 20,
    justifyContent: 'center',
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
    minHeight: 44,
    paddingVertical: 8,
    paddingHorizontal: 14,
    backgroundColor: '#EFF6FF',
    borderRadius: 20,
    justifyContent: 'center',
  },
  chatToggleText: {
    fontSize: 13,
    color: '#2563EB',
    fontWeight: '600',
  },
  newChatBtn: {
    minHeight: 44,
    paddingVertical: 8,
    paddingHorizontal: 14,
    backgroundColor: '#F0FDF4',
    borderRadius: 20,
    justifyContent: 'center',
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
    minHeight: 44,
    paddingVertical: 6,
    paddingHorizontal: 12,
    backgroundColor: '#EFF6FF',
    borderRadius: 14,
    justifyContent: 'center',
  },
  convNewChatText: {
    color: '#2563EB',
    fontSize: 12,
    fontWeight: '600',
  },
  endButton: {
    minHeight: 44,
    paddingVertical: 6,
    paddingHorizontal: 14,
    backgroundColor: '#FEE2E2',
    borderRadius: 14,
    justifyContent: 'center',
  },
  guidanceBanner: {
    marginHorizontal: 16,
    marginTop: 8,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: 12,
    backgroundColor: '#FFF7ED',
  },
  guidanceText: {
    color: '#9A3412',
    fontSize: 13,
    lineHeight: 18,
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
