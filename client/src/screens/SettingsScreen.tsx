import React, {useState, useContext, useEffect} from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  SafeAreaView,
  Alert,
} from 'react-native';
import {AppContext} from '../../App';
import {saveSettings} from '../services/storage';

export const SettingsScreen: React.FC = () => {
  const {settings, updateSettings} = useContext(AppContext);
  const [serverUrl, setServerUrl] = useState(settings.serverUrl);
  const [apiKey, setApiKey] = useState(settings.apiKey);
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    setServerUrl(settings.serverUrl);
    setApiKey(settings.apiKey);
  }, [settings]);

  const handleSave = async () => {
    if (!serverUrl.trim()) {
      Alert.alert('Error', 'Server URL is required');
      return;
    }
    if (!apiKey.trim() || !apiKey.startsWith('sk-')) {
      Alert.alert(
        'Error',
        'Valid OpenAI API key (sk-...) is required',
      );
      return;
    }

    const newSettings = {
      serverUrl: serverUrl.trim(),
      apiKey: apiKey.trim(),
    };
    await saveSettings(newSettings);
    updateSettings(newSettings);
    Alert.alert('Saved', 'Settings saved successfully');
  };

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.form}>
        <Text style={styles.label}>Server URL</Text>
        <TextInput
          style={styles.input}
          value={serverUrl}
          onChangeText={setServerUrl}
          placeholder="192.168.1.100:8765"
          placeholderTextColor="#999"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        <Text style={styles.hint}>
          IP:port of the Windows server on your local network.
        </Text>

        <Text style={styles.label}>OpenAI API Key</Text>
        <View style={styles.keyRow}>
          <TextInput
            style={[styles.input, styles.keyInput]}
            value={apiKey}
            onChangeText={setApiKey}
            placeholder="sk-..."
            placeholderTextColor="#999"
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry={!showKey}
          />
          <TouchableOpacity
            style={styles.toggleBtn}
            onPress={() => setShowKey(!showKey)}>
            <Text>{showKey ? 'Hide' : 'Show'}</Text>
          </TouchableOpacity>
        </View>

        <TouchableOpacity style={styles.saveBtn} onPress={handleSave}>
          <Text style={styles.saveBtnText}>Save</Text>
        </TouchableOpacity>
      </View>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FAFAFA',
  },
  form: {
    padding: 20,
  },
  label: {
    fontSize: 15,
    fontWeight: '600',
    color: '#333',
    marginTop: 20,
    marginBottom: 6,
  },
  input: {
    backgroundColor: '#FFF',
    borderWidth: 1,
    borderColor: '#DDD',
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    fontSize: 15,
    color: '#333',
  },
  hint: {
    fontSize: 12,
    color: '#888',
    marginTop: 4,
  },
  keyRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  keyInput: {
    flex: 1,
  },
  toggleBtn: {
    marginLeft: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: '#EEE',
    borderRadius: 8,
  },
  saveBtn: {
    backgroundColor: '#2196F3',
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 30,
  },
  saveBtnText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: '700',
  },
});
