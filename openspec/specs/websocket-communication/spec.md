# WebSocket Communication

## Purpose
Establish a reliable, real-time WebSocket connection between the Android client and the Windows server for low-latency command transmission. Support both one-shot commands and conversational question/answer flow.

## Requirements

### Requirement: Connection Establishment (Client + Server)
The system SHALL connect to a configurable WebSocket server URL.
#### Scenario: Successful Connection
- GIVEN the user has configured a valid server URL and API key
- WHEN the app starts
- THEN the system SHALL attempt to open a WebSocket connection to `ws://<serverUrl>`
- AND SHALL update the connection status indicator to "connecting"

#### Scenario: Connection Success
- GIVEN the server is reachable and accepting connections
- WHEN the WebSocket `onopen` event fires
- THEN the status indicator SHALL turn green with "Connected" label
- AND SHALL display the connected server URL

### Requirement: Auto-Reconnection (Client)
The system SHALL automatically reconnect when the connection drops.
#### Scenario: Connection Lost
- GIVEN the client was connected
- WHEN the WebSocket `onclose` event fires
- THEN the status indicator SHALL turn gray with "Disconnected" label
- AND SHALL schedule a reconnection attempt

#### Scenario: Reconnection Backoff
- GIVEN the client is in reconnection mode
- WHEN reconnection attempts fail
- THEN the delay SHALL double: 1s, 2s, 4s, 8s, up to 30s maximum
- AND SHALL reset to 1s upon successful connection

### Requirement: Heartbeat Keep-Alive (Client)
The system SHALL maintain connection health with periodic pings.
#### Scenario: Ping Interval
- GIVEN the client is connected
- WHEN 30 seconds have elapsed since the last activity
- THEN the client SHALL send `{"type": "ping"}`
- AND SHALL expect a `{"type": "pong"}` response

#### Scenario: Stale Connection Detection
- GIVEN the client sent a ping
- WHEN no pong is received within 10 seconds
- THEN the server SHALL close the connection
- AND the client SHALL initiate reconnection

### Requirement: Command Messages (Client → Server)
The system SHALL send voice commands to the server.
#### Scenario: Command Transmission
- GIVEN the client has transcribed text
- WHEN the user releases the record button
- THEN the system SHALL send `{"type": "command", "text": "...", "api_key": "sk-..."}`
- AND SHALL wait for a response

#### Scenario: Offline Queue
- GIVEN the client is disconnected
- WHEN the user issues a command
- THEN the system SHALL show a "not connected" error
- AND SHALL NOT queue the command

### Requirement: Result Messages (Server → Client)
The system SHALL receive and display command results.
#### Scenario: Final Result
- GIVEN the agent has completed its task
- WHEN sending the result
- THEN the server SHALL send `{"type": "result", "success": bool, "message": "..."}`
- AND the client SHALL update the command log with the result

### Requirement: Question/Answer Messages (Bidirectional)
The system SHALL support conversational clarification between agent and user.
#### Scenario: Server Questions Client
- GIVEN the agent needs clarification
- WHEN it calls the `ask_user` tool
- THEN the server SHALL send:
  ```json
  {
    "type": "question",
    "id": "q_<timestamp>",
    "message": "Which speaker do you want to connect?",
    "options": ["JBL Flip 5", "Sony SRS-XB12"]
  }
  ```

#### Scenario: Client Answers Server
- GIVEN the client received a question message
- WHEN the user responds
- THEN the client SHALL send:
  ```json
  {
    "type": "answer",
    "id": "q_<timestamp>",
    "text": "JBL Flip 5"
  }
  ```

#### Scenario: Correlation by ID
- GIVEN multiple questions could be pending
- WHEN the client responds
- THEN the `id` field SHALL match the question's `id`
- AND the server SHALL route the answer to the correct agent loop

### Requirement: Error Handling (Client)
The system SHALL handle WebSocket errors gracefully.
#### Scenario: Connection Error
- GIVEN the server URL is unreachable
- WHEN the WebSocket `onerror` event fires
- THEN the status indicator SHALL turn red with "Connection Error" label
- AND SHALL attempt reconnection
- AND SHALL NOT crash the app
