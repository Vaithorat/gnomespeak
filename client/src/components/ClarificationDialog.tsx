import React, {useState} from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  Modal,
  StyleSheet,
  ScrollView,
} from 'react-native';

interface ClarificationDialogProps {
  visible: boolean;
  question: string;
  options: string[];
  onAnswer: (text: string) => void;
  onDismiss: () => void;
}

export const ClarificationDialog: React.FC<ClarificationDialogProps> = ({
  visible,
  question,
  options,
  onAnswer,
  onDismiss,
}) => {
  const [freeText, setFreeText] = useState('');

  const handleSelect = (text: string) => {
    setFreeText('');
    onAnswer(text);
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onDismiss}>
      <View style={styles.overlay}>
        <View style={styles.dialog}>
          <Text style={styles.question}>{question}</Text>

          {options.length > 0 && (
            <ScrollView style={styles.optionsScroll} showsVerticalScrollIndicator={false}>
              <View style={styles.options}>
                {options.map((opt, i) => (
                  <TouchableOpacity
                    key={i}
                    style={styles.optionBtn}
                    onPress={() => handleSelect(opt)}>
                    <Text style={styles.optionText}>{opt}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </ScrollView>
          )}

          <TextInput
            style={styles.input}
            value={freeText}
            onChangeText={setFreeText}
            placeholder="Type your answer..."
            placeholderTextColor="#94A3B8"
            autoFocus={options.length === 0}
          />

          <View style={styles.actions}>
            <TouchableOpacity
              style={[styles.sendBtn, !freeText.trim() && styles.sendBtnDisabled]}
              disabled={!freeText.trim()}
              onPress={() => {
                const text = freeText.trim();
                if (text) {
                  handleSelect(text);
                }
              }}>
              <Text style={styles.sendBtnText}>Send</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.cancelBtn} onPress={onDismiss}>
              <Text style={styles.cancelBtnText}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </View>
    </Modal>
  );
};

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  dialog: {
    backgroundColor: '#FFFFFF',
    borderRadius: 16,
    padding: 24,
    width: '100%',
    maxWidth: 400,
  },
  question: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1E293B',
    marginBottom: 16,
    lineHeight: 22,
  },
  optionsScroll: {
    maxHeight: 200,
  },
  options: {
    marginBottom: 12,
  },
  optionBtn: {
    backgroundColor: '#F1F5F9',
    borderRadius: 10,
    paddingVertical: 11,
    paddingHorizontal: 16,
    marginBottom: 6,
  },
  optionText: {
    fontSize: 14,
    color: '#1E293B',
  },
  input: {
    backgroundColor: '#F8FAFC',
    borderWidth: 1,
    borderColor: '#E2E8F0',
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 14,
    color: '#1E293B',
    marginBottom: 14,
  },
  actions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 10,
  },
  sendBtn: {
    backgroundColor: '#2563EB',
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 20,
  },
  sendBtnDisabled: {
    backgroundColor: '#CBD5E1',
  },
  sendBtnText: {
    color: '#FFFFFF',
    fontSize: 14,
    fontWeight: '600',
  },
  cancelBtn: {
    paddingVertical: 10,
    paddingHorizontal: 20,
  },
  cancelBtnText: {
    color: '#64748B',
    fontSize: 14,
  },
});
