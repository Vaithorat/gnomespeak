import React from 'react';
import {View, Text, FlatList, StyleSheet} from 'react-native';
import {CommandLogEntry} from '../types';

interface Props {
  entries: CommandLogEntry[];
}

const CommandItem: React.FC<{entry: CommandLogEntry}> = ({entry}) => (
  <View
    style={[styles.entry, entry.success ? styles.success : styles.failure]}>
    <View style={[styles.iconDot, entry.success ? styles.iconDotSuccess : styles.iconDotFailure]}>
      <Text style={styles.entryIcon}>{entry.success ? '✓' : '✗'}</Text>
    </View>
    <View style={styles.entryContent}>
      <Text style={styles.transcript}>"{entry.transcript}"</Text>
      <Text style={styles.result}>{entry.result}</Text>
    </View>
  </View>
);

export const CommandLog: React.FC<Props> = ({entries}) => (
  <View style={styles.wrapper} accessible accessibilityLabel="Recent command history">
    <FlatList
      data={entries}
      keyExtractor={item => item.id}
      renderItem={({item}) => <CommandItem entry={item} />}
      contentContainerStyle={styles.container}
      showsVerticalScrollIndicator={false}
      ListEmptyComponent={
        <Text style={styles.empty} accessibilityLiveRegion="polite">
          No commands yet. Hold the mic button to speak.
        </Text>
      }
    />
  </View>
);

const styles = StyleSheet.create({
  wrapper: {
    maxHeight: 220,
  },
  container: {
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  entry: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    padding: 10,
    marginTop: 6,
    borderRadius: 10,
  },
  success: {
    backgroundColor: '#F0FDF4',
  },
  failure: {
    backgroundColor: '#FEF2F2',
  },
  iconDot: {
    width: 24,
    height: 24,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 10,
    marginTop: 2,
  },
  iconDotSuccess: {
    backgroundColor: '#22C55E',
  },
  iconDotFailure: {
    backgroundColor: '#DC2626',
  },
  entryIcon: {
    fontSize: 11,
    fontWeight: 'bold',
    color: '#FFF',
  },
  entryContent: {
    flex: 1,
  },
  transcript: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1E293B',
    fontStyle: 'italic',
  },
  result: {
    fontSize: 12,
    color: '#64748B',
    marginTop: 2,
  },
  empty: {
    textAlign: 'center',
    color: '#94A3B8',
    marginTop: 32,
    fontSize: 13,
  },
});
