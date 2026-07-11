import React, {useState, useEffect, createContext} from 'react';
import {TouchableOpacity, Text, StyleSheet} from 'react-native';
import {NavigationContainer} from '@react-navigation/native';
import {createNativeStackNavigator} from '@react-navigation/native-stack';
import {HomeScreen} from './src/screens/HomeScreen';
import {SettingsScreen} from './src/screens/SettingsScreen';
import {loadSettings} from './src/services/storage';
import {AppSettings} from './src/types';

interface AppContextType {
  settings: AppSettings;
  updateSettings: (s: AppSettings) => void;
}

const DEFAULT_SETTINGS: AppSettings = {
  serverUrl: '',
  openaiKey: '',
  geminiKey: '',
  opencodeKey: '',
  openrouterKey: '',
};

export const AppContext = createContext<AppContextType>({
  settings: DEFAULT_SETTINGS,
  updateSettings: () => {},
});

const Stack = createNativeStackNavigator();

const SettingsIcon: React.FC<{onPress: () => void}> = ({onPress}) => (
  <TouchableOpacity onPress={onPress} style={styles.settingsBtn}>
    <Text style={styles.settingsIcon}>⚙</Text>
  </TouchableOpacity>
);

const App: React.FC = () => {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);

  useEffect(() => {
    loadSettings().then(setSettings);
  }, []);

  return (
    <AppContext.Provider
      value={{
        settings,
        updateSettings: setSettings,
      }}>
      <NavigationContainer>
        <Stack.Navigator
          screenOptions={{
            headerStyle: {backgroundColor: '#FFFFFF'},
            headerTintColor: '#0F172A',
            headerTitleStyle: {fontWeight: '700', fontSize: 18, color: '#0F172A'},
            contentStyle: {backgroundColor: '#FFFFFF'},
            headerShadowVisible: false,
          }}>
          <Stack.Screen
            name="Home"
            component={HomeScreen}
            options={({navigation}) => ({
              title: 'VoiceTalk',
              headerRight: () => (
                <SettingsIcon onPress={() => navigation.navigate('Settings')} />
              ),
            })}
          />
          <Stack.Screen
            name="Settings"
            component={SettingsScreen}
            options={{title: 'Settings'}}
          />
        </Stack.Navigator>
      </NavigationContainer>
    </AppContext.Provider>
  );
};

const styles = StyleSheet.create({
  settingsBtn: {
    padding: 8,
    marginRight: 4,
  },
  settingsIcon: {
    fontSize: 22,
    color: '#64748B',
  },
});

export default App;
