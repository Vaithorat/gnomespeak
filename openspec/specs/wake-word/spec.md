# Wake Word Detection — Planned

## Purpose
Enable hands-free activation by listening for a wake word ("Hey VoiceTalk") before recording, eliminating the need to press the record button.

## Requirements

### Requirement: Wake Word Listening
The system SHALL continuously listen for a configurable wake word in the background.
#### Scenario: Activation
- GIVEN the app is open and the wake word feature is enabled
- WHEN the user speaks the wake word
- THEN the system SHALL trigger voice recording automatically
- AND SHALL provide audio feedback (short vibration or beep)

#### Scenario: Background Listening
- GIVEN the wake word feature is enabled
- WHEN the app is in the foreground
- THEN the system SHALL run a lightweight wake word detection model
- AND SHALL NOT drain excessive battery

### Requirement: Configurable Wake Word
The system SHALL allow the user to change or customize the wake word.
#### Scenario: Change Wake Word
- GIVEN the user is on the settings screen
- WHEN they select "Change Wake Word"
- THEN they SHALL be prompted to speak the new wake word 3 times
- AND SHALL save the new pattern

### Non-Goals
- The system will NOT support wake word detection when the app is in the background
- The system will NOT support multiple simultaneous wake words
