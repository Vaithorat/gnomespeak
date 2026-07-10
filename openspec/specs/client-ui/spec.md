# Client User Interface

## Purpose
Provide an intuitive user interface on the Android device for voice command interaction, agent conversation, connection management, and settings.

## Requirements

### Requirement: Home Screen Layout (Client)
The home screen SHALL display connection status, record button, and command history.
#### Scenario: Screen Structure
- GIVEN the app is open
- WHEN the user views the home screen
- THEN they SHALL see:
  - A connection status bar at the top (colored dot + label)
  - A large circular record button in the center
  - A scrollable command log below

### Requirement: Connection Status Indicator (Client)
The system SHALL indicate WebSocket connection state with a colored dot.
#### Scenario: Status States
- GIVEN the connection status changes
- WHEN the status updates
- THEN the indicator SHALL show:
  - Green dot + "Connected" — WebSocket is open
  - Yellow dot + "Connecting..." — attempting to connect
  - Gray dot + "Disconnected" — not connected, not retrying
  - Red dot + "Connection Error" — error occurred

#### Scenario: Connected URL Display
- GIVEN the client is connected
- WHEN the status bar renders
- THEN the connected server URL SHALL be displayed next to the status label

### Requirement: Command Log (Client)
The system SHALL display a scrollable history of commands and their results.
#### Scenario: Log Entry
- GIVEN a command was sent and a result received
- WHEN the log renders the entry
- THEN it SHALL show:
  - A checkmark (green background) for success or cross (red background) for failure
  - The transcribed text in italics with quotes
  - The result message below

#### Scenario: Log Order
- GIVEN multiple commands have been sent
- WHEN the log displays entries
- THEN the most recent entry SHALL appear at the top

#### Scenario: Empty State
- GIVEN no commands have been sent yet
- WHEN the log area renders
- THEN it SHALL show the placeholder text "No commands yet. Hold the mic button to speak."

### Requirement: Clarification Dialog (Client)
The system SHALL display a dialog when the server asks a question.
#### Scenario: Question Received
- GIVEN the client receives a `{"type": "question"}` message
- WHEN the WebSocket service processes it
- THEN the system SHALL display a modal dialog
- AND SHALL show the question text
- AND SHALL render each option as a tappable button
- AND SHALL provide a free-text input field as fallback

#### Scenario: Option Selection
- GIVEN the dialog shows option buttons
- WHEN the user taps one
- THEN the system SHALL send `{"type": "answer", "id": "<id>", "text": "<selected>"}`
- AND SHALL dismiss the dialog

#### Scenario: Free-Text Answer
- GIVEN the user types in the free-text input
- WHEN they submit
- THEN the system SHALL send the typed text as the answer
- AND SHALL dismiss the dialog

#### Scenario: Block Recording During Question
- GIVEN a question dialog is displayed
- WHEN the user presses the record button
- THEN the record button SHALL be disabled
- AND SHALL show "Please answer the question first"

#### Scenario: Question Timeout
- GIVEN a question dialog has been displayed
- WHEN 60 seconds pass without an answer
- THEN the system SHALL auto-dismiss and send `{"type": "answer", "text": ""}`
- AND SHALL notify the server of the timeout

### Requirement: Settings Screen (Client)
The system SHALL provide a settings screen for server and API key configuration.
#### Scenario: Settings Fields
- GIVEN the user navigates to Settings
- WHEN the screen renders
- THEN it SHALL show:
  - Server URL text input (placeholder: `192.168.1.100:8765`)
  - OpenAI API Key text input (masked, with Show/Hide toggle)
  - Save button

#### Scenario: Validation on Save
- GIVEN the user taps Save
- WHEN the server URL or API key is empty or invalid
- THEN the system SHALL show an alert describing the validation error
- AND SHALL NOT save

#### Scenario: Successful Save
- GIVEN both fields are valid
- WHEN the user taps Save
- THEN the system SHALL persist settings via AsyncStorage
- AND SHALL update the app context
- AND SHALL show a "Saved" confirmation alert

### Requirement: Navigation (Client)
The system SHALL provide navigation between Home and Settings screens.
#### Scenario: Open Settings
- GIVEN the user is on the Home screen
- WHEN they tap the gear icon in the header
- THEN the system SHALL navigate to the Settings screen

#### Scenario: Stack Navigation
- GIVEN the user is on the Settings screen
- WHEN they press the back button
- THEN the system SHALL return to the Home screen
