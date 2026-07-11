import React, {useState, useContext, useEffect} from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  SafeAreaView,
  Alert,
  ScrollView,
} from 'react-native';
import {AppContext} from '../../App';
import {saveSettings} from '../services/storage';

export const SettingsScreen: React.FC = () => {
  const {settings, updateSettings} = useContext(AppContext);
  const [serverUrl, setServerUrl] = useState(settings.serverUrl);
  const [openaiKey, setOpenaiKey] = useState(settings.openaiKey);
  const [geminiKey, setGeminiKey] = useState(settings.geminiKey);
  const [opencodeKey, setOpencodeKey] = useState(settings.opencodeKey);
  const [openrouterKey, setOpenrouterKey] = useState(settings.openrouterKey);
  const [showKeys, setShowKeys] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setServerUrl(settings.serverUrl);
    setOpenaiKey(settings.openaiKey);
    setGeminiKey(settings.geminiKey);
    setOpencodeKey(settings.opencodeKey);
    setOpenrouterKey(settings.openrouterKey);
  }, [settings]);

  const handleSave = async () => {
    if (!serverUrl.trim()) {
      Alert.alert('Error', 'Server URL is required');
      return;
    }
    if (!openaiKey.trim() && !geminiKey.trim() && !opencodeKey.trim() && !openrouterKey.trim()) {
      Alert.alert('Error', 'At least one API key is required');
      return;
    }

    setSaving(true);
    const newSettings = {
      serverUrl: serverUrl.trim(),
      openaiKey: openaiKey.trim(),
      geminiKey: geminiKey.trim(),
      opencodeKey: opencodeKey.trim(),
      openrouterKey: openrouterKey.trim(),
    };
    try {
      await saveSettings(newSettings);
      updateSettings(newSettings);
      Alert.alert('Saved', 'Settings saved successfully');
    } catch {
      Alert.alert('Error', 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView style={styles.form}>
        <Text style={styles.label}>Server URL</Text>
        <TextInput
          style={styles.input}
          value={serverUrl}
          onChangeText={setServerUrl}
          placeholder="192.168.1.100:8765"
          placeholderTextColor="#94A3B8"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
        />
        <Text style={styles.hint}>
          IP:port of the Windows server on your local network.
        </Text>

        <Text style={styles.sectionTitle}>AI Providers</Text>
        <Text style={styles.hint}>
          Fill only the key(s) you want to use. Priority: Gemini &gt; OpenRouter &gt; OpenCode &gt; OpenAI.
        </Text>

        <Text style={styles.providerLabel}>Google Gemini</Text>
        <View style={styles.keyRow}>
          <TextInput
            style={[styles.input, styles.keyInput]}
            value={geminiKey}
            onChangeText={setGeminiKey}
            placeholder="AIza..."
            placeholderTextColor="#94A3B8"
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry={!showKeys}
          />
        </View>

        <Text style={styles.providerLabel}>OpenCode Go</Text>
        <View style={styles.keyRow}>
          <TextInput
            style={[styles.input, styles.keyInput]}
            value={opencodeKey}
            onChangeText={setOpencodeKey}
            placeholder="oc_go_..."
            placeholderTextColor="#94A3B8"
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry={!showKeys}
          />
        </View>

        <Text style={styles.providerLabel}>OpenRouter (free)</Text>
        <View style={styles.keyRow}>
          <TextInput
            style={[styles.input, styles.keyInput]}
            value={openrouterKey}
            onChangeText={setOpenrouterKey}
            placeholder="sk-or-v1-..."
            placeholderTextColor="#94A3B8"
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry={!showKeys}
          />
        </View>

        <Text style={styles.providerLabel}>OpenAI</Text>
        <View style={styles.keyRow}>
          <TextInput
            style={[styles.input, styles.keyInput]}
            value={openaiKey}
            onChangeText={setOpenaiKey}
            placeholder="sk-..."
            placeholderTextColor="#94A3B8"
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry={!showKeys}
          />
        </View>

        <TouchableOpacity
          style={styles.toggleBtn}
          onPress={() => setShowKeys(!showKeys)}>
          <Text style={styles.toggleBtnText}>
            {showKeys ? 'Hide Keys' : 'Show Keys'}
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[styles.saveBtn, saving && styles.saveBtnDisabled]}
          onPress={handleSave}
          disabled={saving}>
          <Text style={styles.saveBtnText}>{saving ? 'Saving...' : 'Save'}</Text>
        </TouchableOpacity>
      </ScrollView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#FFFFFF',
  },
  form: {
    padding: 20,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#475569',
    marginTop: 20,
    marginBottom: 6,
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
  },
  hint: {
    fontSize: 11,
    color: '#94A3B8',
    marginTop: 4,
    marginBottom: 8,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: '#1E293B',
    marginTop: 24,
    marginBottom: 4,
  },
  providerLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: '#475569',
    marginTop: 16,
    marginBottom: 6,
  },
  keyRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  keyInput: {
    flex: 1,
  },
  toggleBtn: {
    marginTop: 16,
    alignSelf: 'center',
    paddingHorizontal: 20,
    paddingVertical: 8,
    backgroundColor: '#F1F5F9',
    borderRadius: 10,
  },
  toggleBtnText: {
    fontSize: 13,
    color: '#475569',
    fontWeight: '500',
  },
  saveBtn: {
    backgroundColor: '#2563EB',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 20,
    marginBottom: 40,
  },
  saveBtnDisabled: {
    backgroundColor: '#93C5FD',
  },
  saveBtnText: {
    color: '#FFFFFF',
    fontSize: 15,
    fontWeight: '700',
  },
});
