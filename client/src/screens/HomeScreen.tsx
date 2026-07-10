import React, {useState, useEffect, useCallback, useContext} from 'react';
import {View, StyleSheet, SafeAreaView} from 'react-native';
import {ConnectionStatus} from '../components/ConnectionStatus';
import {RecordButton} from '../components/RecordButton';
import {CommandLog} from '../components/CommandLog';
import {ClarificationDialog} from '../components/ClarificationDialog';
import {wsService} from '../services/websocket';
import {AppContext} from '../../App';
import {
  CommandLogEntry,
  ConnectionStatus as ConnectionStatusType,
} from '../types';

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

  useEffect(() => {
    wsService.onStatusChange(setConnectionStatus);
    wsService.onResult(result => {
      setLogEntries(prev => {
        for (let i = 0; i < prev.length; i++) {
          if (prev[i].result === 'Sending...') {
            const updated = [...prev];
            updated[i] = {
              ...updated[i],
              result: result.message,
              success: result.success,
            };
            return updated;
          }
        }
        return prev;
      });
    });
    wsService.onQuestion(q => {
      setQuestion({id: q.id, message: q.message, options: q.options});
    });

    if (settings.serverUrl && settings.apiKey) {
      wsService.connect(settings.serverUrl, settings.apiKey);
    }

    return () => {
      wsService.disconnect();
    };
  }, [settings.serverUrl, settings.apiKey]);

  const handleTranscript = useCallback((text: string) => {
    if (question) {
      return;
    }
    const entry: CommandLogEntry = {
      id: Date.now().toString(),
      transcript: text,
      result: 'Sending...',
      success: true,
      timestamp: Date.now(),
    };
    setLogEntries(prev => [entry, ...prev]);
    wsService.send(text);
  }, [question]);

  const handleAnswer = useCallback((text: string) => {
    if (question) {
      wsService.sendAnswer(question.id, text);
      setQuestion(null);
    }
  }, [question]);

  return (
    <SafeAreaView style={styles.container}>
      <ConnectionStatus
        status={connectionStatus}
        serverUrl={settings.serverUrl}
      />
      <View style={styles.content}>
        <RecordButton
          onTranscript={handleTranscript}
          disabled={connectionStatus !== 'connected' || question !== null}
        />
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
    backgroundColor: '#FAFAFA',
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    paddingVertical: 20,
  },
});
