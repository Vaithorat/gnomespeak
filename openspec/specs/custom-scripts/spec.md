# Custom Scripts — Planned

## Purpose
Allow users to define custom voice command → script/action mappings for personalized automation.

## Requirements

### Requirement: Script Mapping Configuration
The system SHALL support user-defined mappings from voice phrases to executable commands or scripts.
#### Scenario: Define a Mapping
- GIVEN the user wants to create a custom command
- WHEN they edit a configuration file or use a settings UI
- THEN they SHALL specify:
  - A trigger phrase or regex pattern
  - A command to execute (PowerShell, batch, or any executable)
  - Optional parameters

#### Scenario: Mapping Example
- GIVEN the user configured: `"open project": "code C:\\Projects\\voicetalk"`
- WHEN they say "open project"
- THEN the system SHALL execute `code C:\Projects\voicetalk`
- AND SHALL return the output as the result

### Requirement: Mappings Storage
The system SHALL store custom script mappings in a config file.
#### Scenario: Storage Location
- GIVEN the user has created custom mappings
- WHEN the server starts
- THEN the system SHALL load mappings from `custom_scripts.json`
- AND SHALL make them available for matching before the intent parser

### Requirement: Priority over Intent Parser
The system SHALL check custom scripts before the general intent parser.
#### Scenario: Override
- GIVEN a custom script mapping matches the spoken text
- WHEN the server processes the command
- THEN the custom script SHALL execute instead of the intent parser
- AND the intent parser SHALL NOT be called

### Non-Goals
- The system will NOT provide a visual script editor
- The system will NOT sandbox custom scripts (they run with server privileges)
