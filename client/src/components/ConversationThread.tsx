import React, {useRef, useEffect, useMemo} from 'react';
import {View, Text, StyleSheet, FlatList} from 'react-native';
import {ConversationMessage} from '../types';

interface Props {
  messages: ConversationMessage[];
  liveText?: string;
  isListening?: boolean;
}

const MessageBubble: React.FC<{message: ConversationMessage}> = ({message}) => {
  const isUser = message.role === 'user';
  const isQuestion = message.role === 'question';
  return (
    <View style={[styles.bubbleRow, isUser ? styles.userRow : styles.assistantRow]}>
      <View style={[
        styles.bubble,
        isUser ? styles.userBubble : isQuestion ? styles.questionBubble : styles.assistantBubble,
      ]}>
        <Text style={[styles.bubbleText, isUser ? styles.userText : styles.assistantText]}>
          {message.text}
        </Text>
        {isQuestion && (
          <Text style={styles.questionHint}>Tap mic to reply</Text>
        )}
      </View>
    </View>
  );
};

export const ConversationThread: React.FC<Props> = ({messages, liveText, isListening}) => {
  const listRef = useRef<FlatList>(null);

  useEffect(() => {
    const t = setTimeout(() => listRef.current?.scrollToEnd({animated: true}), 150);
    return () => clearTimeout(t);
  }, [messages, liveText]);

  const data = useMemo(() => {
    const items: ConversationMessage[] = [...messages];
    if (liveText && isListening) {
      items.push({id: '__live', role: 'user', text: liveText, timestamp: Date.now(), isFinal: false});
    } else if (isListening && !liveText) {
      items.push({id: '__listening', role: 'assistant', text: 'Listening...', timestamp: Date.now(), isFinal: false});
    }
    return items;
  }, [messages, liveText, isListening]);

  return (
    <FlatList
      ref={listRef}
      data={data}
      keyExtractor={item => item.id}
      renderItem={({item}) => <MessageBubble message={item} />}
      contentContainerStyle={styles.listContent}
      style={styles.list}
    />
  );
};

const styles = StyleSheet.create({
  list: {
    flex: 1,
  },
  listContent: {
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  bubbleRow: {
    marginBottom: 8,
    flexDirection: 'row',
  },
  userRow: {
    justifyContent: 'flex-end',
  },
  assistantRow: {
    justifyContent: 'flex-start',
  },
  bubble: {
    maxWidth: '80%',
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: 16,
  },
  userBubble: {
    backgroundColor: '#2563EB',
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    backgroundColor: '#F1F5F9',
    borderBottomLeftRadius: 4,
  },
  questionBubble: {
    backgroundColor: '#FEF3C7',
    borderBottomLeftRadius: 4,
    borderWidth: 1,
    borderColor: '#F59E0B',
  },
  bubbleText: {
    fontSize: 14,
    lineHeight: 20,
  },
  userText: {
    color: '#FFFFFF',
  },
  assistantText: {
    color: '#1E293B',
  },
  questionHint: {
    fontSize: 11,
    color: '#D97706',
    marginTop: 4,
    fontStyle: 'italic',
  },
});
