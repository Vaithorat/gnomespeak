# Multi-Language STT — Planned

## Purpose
Extend speech-to-text support to languages beyond English, with automatic language detection and per-language configuration.

## Requirements

### Requirement: Language Selection
The system SHALL allow the user to configure the speech recognition language.
#### Scenario: Language Setting
- GIVEN the user is on the Settings screen
- WHEN they select "Recognition Language"
- THEN they SHALL choose from a list of supported locales
- AND the selection SHALL be persisted via AsyncStorage

### Requirement: Supported Locales
The system SHALL support a configurable list of Android SpeechRecognizer locales.
#### Scenario: Initial Locales
- GIVEN the app is installed
- WHEN the language selector is opened
- THEN the user SHALL see at least: `en-US` (English US), `es-ES` (Spanish), `fr-FR` (French), `de-DE` (German), `zh-CN` (Chinese Simplified), `ja-JP` (Japanese), `ko-KR` (Korean)

### Requirement: Locale-Aware Recording
The system SHALL pass the selected locale to the speech recognizer.
#### Scenario: Use Selected Locale
- GIVEN the user selected a non-English language
- WHEN recording starts
- THEN the system SHALL pass the configured locale to `Voice.start(locale)`
- AND SHALL return transcribed text in the selected language

### Requirement: Intent Parsing in Other Languages
The system SHALL handle the transcribed text even when it is not in English.
#### Scenario: Non-English Command
- GIVEN the user speaks a command in Spanish
- WHEN the server receives the transcribed Spanish text
- THEN the system SHALL pass it to the OpenAI parser with bilingual system prompt instructions
- AND the fallback parser SHALL NOT be expected to handle non-English

### Non-Goals
- The system will NOT perform language auto-detection
- The system will NOT translate commands — the intent parser must handle the language
- The system will NOT support mixed-language commands
