# Chat Interface

## Purpose
Provide a text-based chat mode alongside voice and conversation modes, allowing users to type messages and receive AI responses in a threaded conversation UI.

## Requirements

### Requirement: Chat Mode Toggle (Client)
The system SHALL provide a toggle to switch between Voice, Conversation, and Chat modes.
#### Scenario: Switch to Chat Mode
- GIVEN the user is on the HomeScreen
- WHEN the user taps the "Chat" button
- THEN the system SHALL switch to Chat mode
- AND SHALL display a text input field with a Send button at the bottom
- AND SHALL display the ConversationThread component for message history

#### Scenario: Switch Back to Voice Mode
- GIVEN the user is in Chat mode
- WHEN the user taps the "Voice" button
- THEN the system SHALL switch back to Voice mode
- AND SHALL display the RecordButton and status bar

### Requirement: Text Input and Send (Client)
The system SHALL allow users to type and send text messages.
#### Scenario: Send a Text Message
- GIVEN the user is in Chat mode
- WHEN the user types text and taps Send (or presses Enter)
- THEN the system SHALL add the message to the chat thread as a user message
- AND SHALL send the text to the server via `wsService.sendWithSession(text, sessionId)`
- AND SHALL clear the input field
- AND SHALL show a waiting indicator

#### Scenario: Empty Message Prevention
- GIVEN the user is in Chat mode
- WHEN the user taps Send with an empty input
- THEN the system SHALL NOT send any message

### Requirement: Session Continuity (Client)
Chat mode SHALL share the same session context as Voice mode.
#### Scenario: Session ID Sharing
- GIVEN the user sends a message in Chat mode
- WHEN the message is sent to the server
- THEN the system SHALL use the same `sessionIdRef` as Voice mode
- AND the server SHALL maintain conversation history across mode switches

### Requirement: Message Display (Client)
The system SHALL display messages in a threaded conversation view.
#### Scenario: User Message Display
- GIVEN a user message is sent
- WHEN it appears in the thread
- THEN it SHALL be displayed as a right-aligned blue bubble

#### Scenario: AI Response Display
- GIVEN the server returns a response
- WHEN it appears in the thread
- THEN it SHALL be displayed as a left-aligned gray bubble

#### Scenario: Question Display
- GIVEN the server asks a clarification question
- WHEN it appears in the thread
- THEN it SHALL be displayed as a left-aligned bubble with orange border

### Requirement: Server Message Handling (Client)
The system SHALL handle server results and questions in Chat mode.
#### Scenario: Result Received
- GIVEN the server sends a result message
- WHEN the app is in Chat mode
- THEN the system SHALL add the result as an assistant message in the chat thread
- AND SHALL clear the waiting state

#### Scenario: Question Received
- GIVEN the server sends a question message
- WHEN the app is in Chat mode
- THEN the system SHALL add the question as a question message in the chat thread
- AND SHALL allow the user to type a response

### Non-Goals
- The system will NOT implement rich media messages (images, files)
- The system will NOT support message editing or deletion
- The system will NOT implement message reactions or threading beyond linear conversation
- The system will NOT support offline message queuing
