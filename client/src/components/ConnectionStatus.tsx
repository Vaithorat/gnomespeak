import React from 'react';
import {View, Text, StyleSheet} from 'react-native';
import {ConnectionStatus as ConnectionStatusType} from '../types';

interface Props {
  status: ConnectionStatusType;
  serverUrl: string;
  compact?: boolean;
}

const STATUS_COLORS: Record<ConnectionStatusType, string> = {
  connected: '#22C55E',
  connecting: '#F59E0B',
  disconnected: '#CBD5E1',
  error: '#DC2626',
};

const STATUS_LABELS: Record<ConnectionStatusType, string> = {
  connected: 'Connected',
  connecting: 'Connecting...',
  disconnected: 'Disconnected',
  error: 'Connection Error',
};

export const ConnectionStatus: React.FC<Props> = ({status, serverUrl, compact}) => (
  <View style={[styles.container, compact ? styles.containerCompact : null]}>
    <View style={styles.dotWrap}>
      <View style={[styles.dot, {backgroundColor: STATUS_COLORS[status]}]} />
    </View>
    {!compact ? (
      <>
        <Text style={styles.text}>{STATUS_LABELS[status]}</Text>
        {status === 'connected' ? (
          <Text style={styles.url}>{serverUrl}</Text>
        ) : null}
      </>
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
  containerCompact: {
    paddingVertical: 4,
    paddingHorizontal: 8,
  },
  dotWrap: {
    padding: 4,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 8,
  },
  text: {
    fontSize: 13,
    color: '#475569',
  },
  url: {
    fontSize: 11,
    color: '#94A3B8',
    marginLeft: 8,
  },
});
