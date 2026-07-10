import React, {useState} from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  Modal,
  StyleSheet,
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
          )}

          <TextInput
            style={styles.input}
            value={freeText}
            onChangeText={setFreeText}
            placeholder="Type your answer..."
            placeholderTextColor="#999"
            autoFocus={options.length === 0}
          />

          <View style={styles.actions}>
            <TouchableOpacity
              style={styles.sendBtn}
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
    backgroundColor: 'rgba(0,0,0,0.5)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  dialog: {
    backgroundColor: '#FFF',
    borderRadius: 14,
    padding: 24,
    width: '100%',
    maxWidth: 400,
  },
  question: {
    fontSize: 17,
    fontWeight: '600',
    color: '#222',
    marginBottom: 18,
    lineHeight: 24,
  },
  options: {
    marginBottom: 14,
  },
  optionBtn: {
    backgroundColor: '#F0F0F0',
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
    marginBottom: 8,
  },
  optionText: {
    fontSize: 15,
    color: '#333',
  },
  input: {
    backgroundColor: '#F8F8F8',
    borderWidth: 1,
    borderColor: '#DDD',
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    color: '#333',
    marginBottom: 14,
  },
  actions: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 10,
  },
  sendBtn: {
    backgroundColor: '#2196F3',
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 20,
  },
  sendBtnText: {
    color: '#FFF',
    fontSize: 15,
    fontWeight: '600',
  },
  cancelBtn: {
    paddingVertical: 10,
    paddingHorizontal: 20,
  },
  cancelBtnText: {
    color: '#888',
    fontSize: 15,
  },
});
