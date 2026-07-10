# Audio Recording & Speech-to-Text

## Purpose
Capture voice input on the Android device and transcribe it to text with high accuracy using on-device speech recognition.

## Requirements

### Requirement: Microphone Access
The system SHALL request and acquire Android microphone permissions at first launch.
#### Scenario: Permission Grant
- GIVEN the user opens the app for the first time
- WHEN the system attempts to start audio recording
- THEN the Android runtime permission dialog SHALL appear
- AND the app SHALL handle both grant and denial gracefully

#### Scenario: Permission Denial
- GIVEN the user denied microphone permission
- WHEN the user presses the record button
- THEN the system SHALL show an explanatory alert
- AND SHALL provide a button to open app settings

### Requirement: Hold-to-Record Interaction
The system SHALL provide a press-and-hold button for recording.
#### Scenario: Start Recording
- GIVEN the user is on the home screen
- WHEN the user presses and holds the mic button
- THEN the system SHALL begin audio capture immediately
- AND SHALL visually indicate recording state (red button, "Listening..." label)

#### Scenario: Stop Recording
- GIVEN the user is currently recording
- WHEN the user releases the mic button
- THEN the system SHALL stop audio capture
- AND SHALL begin transcription of the captured audio

### Requirement: On-Device Speech Recognition
The system SHALL transcribe speech to text using Android's native SpeechRecognizer API.
#### Scenario: Successful Transcription
- GIVEN the user spoke clearly into the microphone
- WHEN the recording stops
- THEN the system SHALL return the transcribed text
- AND SHALL pass the text to the WebSocket service for transmission

#### Scenario: No Speech Detected
- GIVEN the user pressed the record button
- WHEN no speech is detected before release
- THEN the system SHALL not send an empty command
- AND SHALL return to idle state without action

#### Scenario: Recognition Error
- GIVEN the SpeechRecognizer encounters an error
- WHEN the error callback fires
- THEN the system SHALL log the error
- AND SHALL reset to idle state
- AND SHALL notify the user of the failure

### Requirement: Language Support
The system SHALL default to US English (`en-US`) for speech recognition.
#### Scenario: Default Language
- GIVEN the app has no language override configured
- WHEN speech recognition starts
- THEN the locale SHALL be `en-US`
