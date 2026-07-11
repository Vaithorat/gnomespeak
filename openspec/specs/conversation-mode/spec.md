# Conversation Mode

## Purpose
Replace the current hold-to-talk pattern with a continuous, always-listening conversation mode (like Gemini or Alexa). The mic stays open, speech is recognized continuously, and transcripts are sent to the server on silence detection. The AI can ask follow-up questions and the user can keep speaking without pressing a button.

## Requirements

### Requirement: Conversation Mode Toggle (Client)
The client SHALL provide a tap-to-toggle between idle and always-listening conversation mode.
#### Scenario: Enter Conversation Mode
- GIVEN the app is in idle state
- WHEN the user taps the mic button once (not hold)
- THEN the client SHALL enter conversation mode
- AND SHALL show a persistent "Listening..." indicator
- AND SHALL start continuous speech recognition
- AND SHALL NOT require the user to hold the button

#### Scenario: Exit Conversation Mode
- GIVEN the app is in conversation mode
- WHEN the user taps the mic button again
- THEN the client SHALL stop speech recognition
- AND SHALL return to idle state

### Requirement: Continuous Speech Recognition (Client)
The client SHALL run on-device STT continuously while in conversation mode.
#### Scenario: Start Continuous Recognition
- GIVEN the client enters conversation mode
- WHEN `Voice.start('en-US')` is called
- THEN the client SHALL accumulate speech results
- AND SHALL display the live transcript in a conversation bubble
- AND SHALL handle STT errors gracefully (restart recognition on error 5/6, show error on persistent failures)

#### Scenario: Restart on Final Result
- GIVEN a speech segment has been finalized and sent
- WHEN the client is still in conversation mode
- THEN the client SHALL call `Voice.destroy()` and `Voice.start()` again to begin listening for the next utterance
- AND SHALL NOT show any interruption to the user

#### Scenario: Recognition Fails Persistently
- GIVEN the STT engine returns 3 consecutive errors
- WHEN the client is in conversation mode
- THEN the client SHALL exit conversation mode
- AND SHALL notify the user with "Speech recognition unavailable"

### Requirement: Silence-Based Send (Client)
The client SHALL detect when the user has stopped speaking and automatically send the transcript to the server.
#### Scenario: Send on Silence
- GIVEN the user is speaking and `onSpeechResults` fires with partial text
- WHEN no new speech results arrive for 1.5 seconds (silence threshold)
- THEN the client SHALL finalize the current transcript
- AND SHALL send it to the server via `wsService.send()`
- AND SHALL show the transcript as a sent message in the conversation thread

#### Scenario: No Speech Detected
- GIVEN the client is in conversation mode
- WHEN 15 seconds pass with no speech detected
- THEN the client SHALL show a "Tap to speak or I'm still listening..." hint
- AND SHALL NOT send an empty transcript
- AND SHALL keep listening

#### Scenario: Abort Send on New Speech
- GIVEN the silence timer is counting down after a pause
- WHEN the user starts speaking again (new `onSpeechResults` fires)
- THEN the client SHALL reset the silence timer
- AND SHALL continue accumulating the transcript

### Requirement: Conversation Thread Display (Client)
The client SHALL display the ongoing conversation as a scrollable thread of messages.
#### Scenario: Show Transcript Bubble
- GIVEN the user speaks a command
- WHEN the transcript is sent to the server
- THEN the client SHALL display the user's words in a right-aligned bubble

#### Scenario: Show AI Response
- GIVEN a server result arrives
- WHEN the result is received
- THEN the client SHALL display the AI response in a left-aligned bubble
- AND SHALL scroll the thread to show the latest message

#### Scenario: Show Clarification Question
- GIVEN the server sends a `question` message
- WHEN the client receives it
- THEN the client SHALL display the question in a left-aligned bubble
- AND SHALL keep listening for the user's spoken answer
- AND SHALL send the next transcript as the answer

#### Scenario: Show Connection Status
- GIVEN the client is in conversation mode
- WHEN the WebSocket connection drops
- THEN the client SHALL show a disconnected warning in the thread
- AND SHALL keep the conversation visible
- AND SHALL exit conversation mode

### Requirement: Conversation Landing Page (Client)
The client SHALL replace the current status-bar layout with a conversation-thread layout when in conversation mode.
#### Scenario: Start New Session
- GIVEN no conversation exists
- WHEN the user enters conversation mode
- THEN the client SHALL show a new empty thread with a "Listening..." placeholder at the bottom
- AND SHALL hide the old status-bar view

#### Scenario: Return to Simple Mode
- GIVEN a conversation thread is shown
- WHEN the user taps the back/exit button
- THEN the client SHALL exit conversation mode
- AND SHALL return to the simple hold-to-talk view
- AND SHALL clear the conversation thread

### Requirement: Multi-Turn State Management (Server)
The server SHALL maintain session state across multiple voice turns within a conversation.
#### Scenario: Follow-Up Question Answered
- GIVEN the server sent a `question` message
- WHEN the client sends an `answer` message
- THEN the server SHALL continue processing with the answer context
- AND SHALL send a `result` or another `question` as needed
- AND SHALL NOT end the session

#### Scenario: New Command in Active Session
- GIVEN an active conversation session exists
- WHEN the client sends a new `command` message (not an `answer`)
- THEN the server SHALL treat it as a new top-level command
- AND SHALL clear any pending question state
- AND SHALL process the command fresh

### Requirement: Conversation Protocol (Integration)
The protocol SHALL support a persistent session identifier for multi-turn conversations.
#### Scenario: Session ID in Messages
- GIVEN the client enters conversation mode
- WHEN the client sends the first command
- THEN the client SHALL include a `"session_id"` field in the command message
- AND SHALL reuse the same session_id for all messages in this conversation
- AND SHALL generate a new session_id next time conversation mode starts

#### Scenario: Server Session Tracking
- GIVEN the server receives a command with a `session_id`
- WHEN a session with that ID already exists
- THEN the server SHALL continue the existing AI conversation context
- AND SHALL NOT create a new agent loop

### Requirement: Visual Indicator Redesign (Client)
The client SHALL redesign the main screen to support both conversation and simple modes.
#### Scenario: Conversation Mode Layout
- GIVEN the client is in conversation mode
- THEN the client SHALL show:
  - A top bar with connection status and "End" button
  - A scrollable conversation thread in the middle
  - A pulsing mic indicator at the bottom showing "Listening..."
- AND SHALL NOT show the status bar or hold-to-talk button

#### Scenario: Simple Mode Layout (Preserved)
- GIVEN the client is NOT in conversation mode
- THEN the client SHALL show the existing layout:
  - Connection status bar
  - Hold-to-talk mic button
  - Pipeline status bar
  - Command log

### Non-Goals
- The system will NOT implement wake-word activation ("Hey VoiceTalk") — conversation mode is manually toggled
- The system will NOT implement streaming AI responses — results arrive as complete messages
- The system will NOT implement voice activity detection (VAD) on-device — silence detection uses STT result timing
- The system will NOT support multiple simultaneous conversations
- The system will NOT implement push-to-talk while in conversation mode
- The system will NOT transcribe the AI's spoken responses (text-only client)
- The system will NOT persist conversation history across app restarts
