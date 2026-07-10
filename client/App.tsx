import React, {useState, useEffect, createContext} from 'react';
import {TouchableOpacity, Text} from 'react-native';
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

export const AppContext = createContext<AppContextType>({
  settings: {serverUrl: '', apiKey: ''},
  updateSettings: () => {},
});

const Stack = createNativeStackNavigator();

const SettingsIcon: React.FC<{onPress: () => void}> = ({onPress}) => (
  <TouchableOpacity onPress={onPress}>
    <Text style={{fontSize: 22, color: '#2196F3'}}>{'\u2699'}</Text>
  </TouchableOpacity>
);

const App: React.FC = () => {
  const [settings, setSettings] = useState<AppSettings>({
    serverUrl: '',
    apiKey: '',
  });

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
        <Stack.Navigator>
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

export default App;
