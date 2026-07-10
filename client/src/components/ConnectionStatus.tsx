import React from 'react';
import {View, Text, StyleSheet} from 'react-native';
import {ConnectionStatus as ConnectionStatusType} from '../types';

interface Props {
  status: ConnectionStatusType;
  serverUrl: string;
}

const STATUS_COLORS: Record<ConnectionStatusType, string> = {
  connected: '#4CAF50',
  connecting: '#FFC107',
  disconnected: '#9E9E9E',
  error: '#F44336',
};

const STATUS_LABELS: Record<ConnectionStatusType, string> = {
  connected: 'Connected',
  connecting: 'Connecting...',
  disconnected: 'Disconnected',
  error: 'Connection Error',
};

export const ConnectionStatus: React.FC<Props> = ({status, serverUrl}) => (
  <View style={styles.container}>
    <View style={[styles.dot, {backgroundColor: STATUS_COLORS[status]}]} />
    <Text style={styles.text}>{STATUS_LABELS[status]}</Text>
    {status === 'connected' ? (
      <Text style={styles.url}>{serverUrl}</Text>
    ) : null}
  </View>
);

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 8,
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginRight: 8,
  },
  text: {
    fontSize: 14,
    color: '#333',
  },
  url: {
    fontSize: 12,
    color: '#666',
    marginLeft: 8,
  },
});
