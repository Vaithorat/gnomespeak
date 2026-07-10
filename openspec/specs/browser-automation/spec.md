# Browser Automation

## Purpose
Control web browsers via voice — navigate to websites, search the web, and open YouTube content. The AI agent drives the intelligence; the server simply opens URLs in the default browser.

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

### Requirement: YouTube Search & Play (Server)
The system SHALL open YouTube search results for a query.
#### Scenario: Play via YouTube Search
- GIVEN the user says "play despacito"
- WHEN the command executes
- THEN the system SHALL construct `https://www.youtube.com/results?search_query=<encoded_query>`
- AND SHALL open it in the default browser
- AND SHALL return "Opened YouTube search results for 'despacito'"
- AND the user can click the first video to play

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
- THEN the AI SHALL call `browser_search` or construct a specific YouTube search URL including the creator name
- AND SHALL let the user know the results are ready

### Requirement: Tool Definitions (Integration)
The system SHALL expose browser commands as OpenAI function-calling tools.
#### Scenario: Tool Inventory
The system SHALL register these browser tools:
- `browser_navigate` — Open a URL (param: url)
- `browser_search` — Web search (params: query, engine?)
- `yt_play` — Open YouTube search results (param: query)

### Non-Goals
- The system will NOT install or manage browser drivers
- The system will NOT automate clicks or page interactions
- The system will NOT control browser tabs or windows
- The system will NOT scrape page content
