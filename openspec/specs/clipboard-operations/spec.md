# Clipboard Operations — Planned

## Purpose
Read from and write to the Windows system clipboard via voice commands.

## Requirements

### Requirement: Copy to Clipboard
The system SHALL store text from voice commands into the clipboard.
#### Scenario: Copy Text
- GIVEN the user says "copy hello world" or "copy this text to clipboard"
- WHEN the command is parsed
- THEN the system SHALL place the spoken text into the Windows clipboard
- AND SHALL return success with "Copied to clipboard: {text}"

### Requirement: Paste from Clipboard
The system SHALL simulate a paste operation.
#### Scenario: Paste
- GIVEN the user says "paste" or "paste clipboard"
- WHEN the command is parsed
- THEN the system SHALL simulate Ctrl+V keystroke
- AND SHALL return success

### Requirement: Read Clipboard
The system SHALL read and return the current clipboard contents.
#### Scenario: Read Back
- GIVEN the user says "what's in my clipboard" or "read clipboard"
- WHEN the command is parsed
- THEN the system SHALL read the current clipboard content
- AND SHALL return it as the result message

### Non-Goals
- The system will NOT support clipboard history
- The system will NOT handle images or binary clipboard data
