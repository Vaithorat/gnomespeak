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
  Platform,
} from 'react-native';
import Voice, {
  SpeechResultsEvent,
  SpeechErrorEvent,
} from '@react-native-voice/voice';

interface Props {
  onTranscript: (text: string) => void;
  disabled: boolean;
}

export const RecordButton: React.FC<Props> = ({onTranscript, disabled}) => {
  const [isRecording, setIsRecording] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [hasPermission, setHasPermission] = useState<boolean | null>(null);
  const transcriptRef = useRef('');

  useEffect(() => {
    requestPermission();
  }, []);

  const requestPermission = async () => {
    try {
      const granted = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,
        {
          title: 'Microphone Permission',
          message:
            'VoiceTalk needs access to your microphone to capture voice commands.',
          buttonPositive: 'Grant',
          buttonNegative: 'Deny',
          buttonNeutral: 'Ask Later',
        },
      );
      setHasPermission(granted === PermissionsAndroid.RESULTS.GRANTED);
    } catch {
      setHasPermission(false);
    }
  };

  const showPermissionAlert = () => {
    Alert.alert(
      'Microphone Required',
      'VoiceTalk needs microphone access to work. Please enable it in Settings.',
      [
        {text: 'Cancel', style: 'cancel'},
        {text: 'Open Settings', onPress: () => Linking.openSettings()},
      ],
    );
  };

  const onSpeechResults = useCallback((e: SpeechResultsEvent) => {
    if (e.value?.[0]) {
      transcriptRef.current = e.value[0];
    }
  }, []);

  const onSpeechError = useCallback(
    (e: SpeechErrorEvent) => {
      console.error('STT Error:', e.error?.message);
      setIsRecording(false);
      setIsProcessing(false);
      Alert.alert(
        'Recognition Error',
        e.error?.message || 'Speech recognition failed. Please try again.',
      );
    },
    [],
  );

  const startRecording = useCallback(async () => {
    if (!hasPermission) {
      if (hasPermission === null) {
        await requestPermission();
      }
      if (!hasPermission) {
        showPermissionAlert();
        return;
      }
    }
    try {
      transcriptRef.current = '';
      setIsRecording(true);
      await Voice.start('en-US');
      Voice.onSpeechResults = onSpeechResults;
      Voice.onSpeechError = onSpeechError;
    } catch (e) {
      console.error('Failed to start recording:', e);
      setIsRecording(false);
    }
  }, [onSpeechResults, onSpeechError, hasPermission]);

  const stopRecording = useCallback(async () => {
    try {
      setIsRecording(false);
      setIsProcessing(true);
      await Voice.stop();
      Voice.destroy();
      const text = transcriptRef.current.trim();
      if (text) {
        onTranscript(text);
      }
      setIsProcessing(false);
    } catch (e) {
      console.error('Failed to stop recording:', e);
      setIsRecording(false);
      setIsProcessing(false);
    }
  }, [onTranscript]);

  return (
    <TouchableOpacity
      onPressIn={startRecording}
      onPressOut={stopRecording}
      disabled={disabled || isProcessing || hasPermission === false}
      activeOpacity={0.7}
      style={[
        styles.button,
        isRecording ? styles.buttonRecording : null,
        disabled || isProcessing || hasPermission === false
          ? styles.buttonDisabled
          : null,
      ]}>
      {isProcessing ? (
        <ActivityIndicator size="large" color="#FFF" />
      ) : (
        <Text style={styles.icon}>{isRecording ? '🔴' : '🎤'}</Text>
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
  );
};

const styles = StyleSheet.create({
  button: {
    width: 120,
    height: 120,
    borderRadius: 60,
    backgroundColor: '#2196F3',
    justifyContent: 'center',
    alignItems: 'center',
    alignSelf: 'center',
    elevation: 4,
    shadowColor: '#000',
    shadowOffset: {width: 0, height: 2},
    shadowOpacity: 0.25,
    shadowRadius: 4,
  },
  buttonRecording: {
    backgroundColor: '#F44336',
  },
  buttonDisabled: {
    backgroundColor: '#BDBDBD',
  },
  icon: {
    fontSize: 36,
  },
  label: {
    color: '#FFF',
    fontSize: 12,
    marginTop: 4,
    fontWeight: '600',
  },
});
