import React from 'react';
import {View, Text, FlatList, StyleSheet} from 'react-native';
import {CommandLogEntry} from '../types';

interface Props {
  entries: CommandLogEntry[];
}

const CommandItem: React.FC<{entry: CommandLogEntry}> = ({entry}) => (
  <View
    style={[styles.entry, entry.success ? styles.success : styles.failure]}>
    <Text style={styles.entryIcon}>{entry.success ? '\u2713' : '\u2717'}</Text>
    <View style={styles.entryContent}>
      <Text style={styles.transcript}>"{entry.transcript}"</Text>
      <Text style={styles.result}>{entry.result}</Text>
    </View>
  </View>
);

export const CommandLog: React.FC<Props> = ({entries}) => (
  <FlatList
    data={entries}
    keyExtractor={item => item.id}
    renderItem={({item}) => <CommandItem entry={item} />}
    contentContainerStyle={styles.container}
    ListEmptyComponent={
      <Text style={styles.empty}>
        No commands yet. Hold the mic button to speak.
      </Text>
    }
  />
);

const styles = StyleSheet.create({
  container: {
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  entry: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    padding: 12,
    marginTop: 8,
    borderRadius: 8,
  },
  success: {
    backgroundColor: '#E8F5E9',
  },
  failure: {
    backgroundColor: '#FFEBEE',
  },
  entryIcon: {
    fontSize: 18,
    fontWeight: 'bold',
    marginRight: 10,
    marginTop: 2,
  },
  entryContent: {
    flex: 1,
  },
  transcript: {
    fontSize: 15,
    fontWeight: '600',
    color: '#333',
    fontStyle: 'italic',
  },
  result: {
    fontSize: 13,
    color: '#555',
    marginTop: 2,
  },
  empty: {
    textAlign: 'center',
    color: '#999',
    marginTop: 32,
    fontSize: 14,
  },
});
