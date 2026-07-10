# Media Player

## Purpose
Play songs and media via voice command. The AI agent searches YouTube (by opening search results in browser) and local files, then plays the best match.

## Requirements

### Requirement: YouTube via Browser (Server)
The system SHALL open YouTube search results for requested songs.
#### Scenario: Open YouTube Search
- GIVEN the user says "play despacito"
- WHEN the yt_play tool executes
- THEN the system SHALL construct `https://www.youtube.com/results?search_query=<encoded_query>`
- AND SHALL open it in the default browser
- AND SHALL return "Opened YouTube search results for '{query}'"

#### Scenario: Creator-Specific Search
- GIVEN the user says "play despacito by luis fonsi"
- WHEN the command executes
- THEN the AI agent SHALL construct the search URL including the creator name
- AND SHALL open the YouTube search results

### Requirement: Local File Playback (Server)
The system SHALL search local music folders for matching files.
#### Scenario: Find Local File
- GIVEN no YouTube result or local playback is preferred
- WHEN the tool searches local files
- THEN the system SHALL scan these directories:
  - `%USERPROFILE%\Music\`
  - `%USERPROFILE%\Downloads\`
- AND SHALL match the query against filenames (case-insensitive substring)

#### Scenario: Play Local File
- GIVEN a matching local file is found
- WHEN the tool initiates playback
- THEN the system SHALL launch the file with its default application via `os.startfile`
- AND SHALL return "Playing {filename} from local files"

#### Scenario: Multiple Matches
- GIVEN multiple local files match the query
- WHEN the tool finds them
- THEN the agent SHALL call `ask_user` to let the user pick via the phone
- AND SHALL wait for the selection

### Requirement: Volume Control (Server)
The system SHALL support volume adjustment.
#### Scenario: Set Volume
- GIVEN the user says "volume 50%" or "volume up" / "volume down"
- WHEN the tool executes
- THEN the system SHALL adjust the system master volume using Windows Core Audio API or nircmd
- AND SHALL return the new volume level

### Requirement: No Client-Side Changes (Client)
The system SHALL handle media playback entirely on the server.
#### Scenario: Client Receives Result Only
- GIVEN the server is playing media
- WHEN the tool completes
- THEN the client SHALL only receive the result message
- AND SHALL NOT need any media-specific UI
