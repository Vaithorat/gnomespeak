# Browser Automation

## Purpose
Control the web browser programmatically via voice commands — navigate to websites, search the web, open YouTube content, and simulate keyboard interactions. The AI agent drives the intelligence; the server opens URLs and sends keyboard shortcuts via pyautogui.

## Requirements

### Requirement: URL Navigation (Server)
The system SHALL open URLs in the default web browser using `webbrowser.open()`.
#### Scenario: Navigate to URL
- GIVEN the user says "open youtube.com" or "go to github.com"
- WHEN the command is parsed
- THEN the system SHALL prepend `https://` if no protocol is specified
- AND SHALL open the URL in the default browser

#### Scenario: Known Sites
- GIVEN the user says a well-known site name without .com (e.g., "youtube", "gmail")
- WHEN the LLM parses the command
- THEN the AI SHALL recognize it as a website and output `browser_navigate` with the .com URL

### Requirement: Web Search (Server)
The system SHALL search the web via browser.
#### Scenario: Search via URL
- GIVEN the user says "search for React Native tutorials"
- WHEN the command executes
- THEN the system SHALL construct the search engine URL with the encoded query
- AND SHALL open it in the default browser

#### Scenario: Configurable Engine
- GIVEN the user says "search for AI news on bing"
- WHEN the command executes
- THEN the system SHALL use the specified search engine (google, bing, duckduckgo)

### Requirement: YouTube Integration (Server)
The system SHALL open YouTube search results and play videos autonomously.
#### Scenario: Play via yt_play
- GIVEN the user says "play despacito"
- WHEN the `yt_play` tool executes
- THEN the system SHALL search YouTube via yt-dlp
- AND SHALL open the first video's watch page
- AND SHALL call `media_control(action='play_pause')` to ensure playback
- AND SHALL NOT require user interaction

#### Scenario: Browse via yt_search
- GIVEN the user says "search YouTube for relaxing music"
- WHEN the `yt_search` tool executes
- THEN the system SHALL open the YouTube search results page
- AND SHALL return the results to the LLM for presentation

### Requirement: Keyboard Simulation (Server)
The system SHALL simulate keyboard shortcuts for browser and media control via pyautogui.
#### Scenario: Play/Pause Video
- GIVEN a YouTube video is open in the browser
- WHEN `media_control(action='play_pause')` executes
- THEN the system SHALL press the Space key via pyautogui
- AND SHALL return "Toggled play/pause (Space)"

#### Scenario: Volume Control via Media Keys
- GIVEN the user says "volume up" or "mute"
- WHEN the media_control tool executes
- THEN the system SHALL press the appropriate media key (volume_up, volume_down, mute)

#### Scenario: Fullscreen Toggle
- GIVEN a video is playing in the browser
- WHEN `media_control(action='fullscreen')` executes
- THEN the system SHALL press F11 to toggle fullscreen

#### Scenario: Browser Navigation Keys
- GIVEN the user says "go back" or "refresh"
- WHEN the media_control tool executes
- THEN the system SHALL press the appropriate key (Escape, F5, etc.)

### Requirement: Single-Tab Execution (Server)
The system SHALL avoid opening multiple browser tabs for a single task.
#### Scenario: One Tool Does Everything
- GIVEN the user says "open firefox, go to youtube and search golmaal 3 and play the first video"
- WHEN the LLM processes this
- THEN the LLM SHALL call ONLY `yt_play` with the full query
- AND SHALL NOT call `browser_navigate` or `yt_search` before `yt_play`
- AND SHALL follow up with `media_control(action='play_pause')` to start playback

#### Scenario: No Duplicate URLs
- GIVEN a video page is already open
- WHEN the user says "play the video"
- THEN the system SHALL use `media_control(action='play_pause')` instead of opening the URL again

### Requirement: LLM-Driven Intelligence (Integration)
The system SHALL rely on the AI agent for smart behavior rather than hard-coded logic.
#### Scenario: AI Determines URLs
- GIVEN the user says complex instructions
- WHEN the agent processes them
- THEN the AI SHALL determine the appropriate URL to open using its training data
- AND SHALL call the `browser_navigate` tool with the best URL

#### Scenario: Multi-Step Reasoning
- GIVEN the user says "play despacito by luis fonsi"
- WHEN the agent processes this
- THEN the AI SHALL call `yt_play` with the full query including creator name
- AND SHALL call `media_control(action='play_pause')` to ensure playback
- AND SHALL inform the user when complete

### Requirement: Tool Definitions (Integration)
The system SHALL expose browser commands as AI function-calling tools.
#### Scenario: Tool Inventory
The system SHALL register these browser tools:
- `browser_navigate` — Open a URL (param: url)
- `browser_search` — Web search (params: query, engine?)
- `yt_play` — Search YouTube and play first video (param: query)
- `yt_search` — Open YouTube search results (param: query)
- `yt_results` — Fetch top 10 YouTube results (param: query)
- `media_control` — Keyboard simulation for browser/media (param: action)

### Non-Goals
- The system will NOT install or manage browser drivers
- The system will NOT take screenshots or read page content (no Selenium/Playwright)
- The system will NOT control browser tabs or windows beyond opening URLs
- The system will NOT fill forms or interact with page elements
- The system will NOT manage cookies or browser sessions
