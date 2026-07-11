# YouTube Viewing

## Purpose
Search and play YouTube videos autonomously via voice commands. The AI agent drives search intelligence; the server searches via yt-dlp, opens video pages in the default browser, and uses keyboard simulation to ensure playback starts. The entire flow — from voice command to video playing — executes without user intervention.

## Requirements

### Requirement: Autonomous Search & Play (Server)
The system SHALL find a video by search query and open its watch page with autoplay — all in a single tool call.
#### Scenario: Play First Match
- GIVEN the user says "play despacito"
- WHEN the `yt_play` tool executes
- THEN the server SHALL use yt-dlp to search YouTube for the query
- AND SHALL extract the first video ID from the search results
- AND SHALL construct `https://www.youtube.com/watch?v={video_id}&autoplay=1`
- AND SHALL open it in the default browser
- AND SHALL return structured data: `{"url": "...", "title": "...", "fallback": false}`

#### Scenario: Search Fails
- GIVEN no video ID can be found via yt-dlp
- WHEN the tool executes
- THEN the system SHALL open the YouTube search results page as fallback
- AND SHALL return `{"url": "...", "title": null, "fallback": true, "query": "..."}`

#### Scenario: Creator-Specific Search
- GIVEN the user says "play despacito by luis fonsi"
- WHEN the `yt_play` tool executes
- THEN the AI agent SHALL pass the full query including creator name
- AND the server SHALL search with the full query string
- AND SHALL open the first matching video

### Requirement: Auto-Play via Keyboard Simulation (Server)
The system SHALL ensure videos start playing after opening, even when browser autoplay is blocked.
#### Scenario: Auto-Chain After yt_play
- GIVEN the `yt_play` tool has opened a video URL
- WHEN the tool returns successfully
- THEN the system SHALL automatically call `media_control(action='play_pause')`
- AND SHALL press the Space key to toggle playback
- AND SHALL return the combined result to the LLM

#### Scenario: Retry if Video Still Paused
- GIVEN the user reports the video is not playing
- WHEN the LLM receives a "video not playing" context
- THEN the LLM SHALL call `media_control(action='play_pause')` again
- AND SHALL NOT open the same URL a second time

### Requirement: YouTube Search Without Playing (Server)
The system SHALL support browsing YouTube results without auto-playing.
#### Scenario: Open Search Results
- GIVEN the user says "search YouTube for relaxing music"
- WHEN the `yt_search` tool executes
- THEN the system SHALL construct the YouTube search URL
- AND SHALL open it in the default browser
- AND SHALL return "Opened YouTube search results for '{query}'"

#### Scenario: Fetch Results as Data
- GIVEN the user wants to pick a specific video
- WHEN the `yt_results` tool executes
- THEN the system SHALL use yt-dlp to fetch top 10 results
- AND SHALL return structured data with video IDs and titles
- AND SHALL format results as a numbered list for the LLM to present

### Requirement: Pick from Search Results (Integration)
The system SHALL allow the user to select a specific video from results.
#### Scenario: Present Options to User
- GIVEN `yt_results` returns multiple videos
- WHEN the LLM processes the results
- THEN the LLM SHALL call `ask_user` with the top result titles
- AND SHALL wait for the user to select one
- AND SHALL open the selected video via `browser_navigate`

### Requirement: Play by URL or Title (Server)
The system SHALL play a video given its title or known URL.
#### Scenario: Play by Video Title
- GIVEN the user says "play never gonna give you up"
- WHEN the command executes
- THEN the system SHALL search YouTube for the exact title
- AND SHALL open the first result's watch page with autoplay

#### Scenario: Play by Known Video ID
- GIVEN the user says "open youtube video dQw4w9WgXcQ"
- WHEN the AI agent processes it
- THEN the system SHALL construct `https://www.youtube.com/watch?v=dQw4w9WgXcQ&autoplay=1`
- AND SHALL open it in the browser
- AND SHALL call `media_control(action='play_pause')` to start playback

### Requirement: Playlist Support (Server)
The system SHALL open YouTube playlists when requested.
#### Scenario: Open Playlist
- GIVEN the user says "play my liked videos playlist" or "open youtube playlist"
- WHEN the AI agent processes it
- THEN the AI SHALL construct `https://www.youtube.com/playlist?list={playlist_id}` or search for the playlist
- AND SHALL open it in the browser

### Requirement: Channel Support (Server)
The system SHALL navigate to YouTube channels.
#### Scenario: Open Channel
- GIVEN the user says "open youtube channel mrbeast"
- WHEN the AI agent processes it
- THEN the AI SHALL construct `https://www.youtube.com/@mrbeast` or search for the channel
- AND SHALL open it in the browser

### Requirement: Search via yt-dlp (Server)
The system SHALL use yt-dlp for reliable YouTube search instead of HTML scraping.
#### Scenario: yt-dlp Search
- GIVEN a YouTube search is needed
- WHEN the server queries yt-dlp
- THEN the system SHALL run `yt-dlp --flat-playlist --dump-json "ytsearch{count}:{query}"`
- AND SHALL parse the JSON output to extract video IDs and titles
- AND SHALL handle yt-dlp errors gracefully (timeout, network, no results)

#### Scenario: yt-dlp Not Installed
- GIVEN yt-dlp is not available
- WHEN a YouTube search is attempted
- THEN the system SHALL fall back to opening the YouTube search URL directly
- AND SHALL return a fallback result indicating yt-dlp is unavailable

### Requirement: Tool Definitions (Integration)
The system SHALL expose YouTube commands as AI function-calling tools.
#### Scenario: Tool Inventory
The system SHALL register these tools:
- `yt_play` — Search YouTube and open the first matching video with autoplay + auto-play via keyboard (param: query)
- `yt_search` — Open YouTube search results page for browsing (param: query)
- `yt_results` — Fetch top 10 YouTube results with titles and IDs (param: query)
- `browser_navigate` — Open any URL (used for channels, playlists, specific videos)
- `media_control` — Keyboard simulation for play/pause (used after yt_play to ensure playback)

### Requirement: Single-Tab Execution (Server)
The system SHALL avoid opening multiple browser tabs for a single YouTube task.
#### Scenario: One Tool Does Everything
- GIVEN the user says "open firefox, go to youtube and search golmaal 3 and play the first video"
- WHEN the LLM processes this multi-step request
- THEN the LLM SHALL call ONLY `yt_play` with the full query
- AND SHALL NOT call `browser_navigate` or `yt_search` separately
- AND SHALL follow up with `media_control(action='play_pause')` to ensure playback

### Requirement: Error Recovery (Server)
The system SHALL recover from YouTube playback failures.
#### Scenario: yt_play Fails
- GIVEN `yt_play` returns `fallback: true`
- WHEN the LLM sees the fallback result
- THEN the LLM SHALL inform the user that search results are open
- AND SHALL offer to play a specific video from the results

#### Scenario: Video Region-Restricted
- GIVEN a video cannot be played due to region restrictions
- WHEN the system detects this
- THEN the system SHALL return the error message to the LLM
- AND the LLM SHALL suggest an alternative video

### Non-Goals
- The system will NOT inject ads or skip ads
- The system will NOT manage YouTube accounts or authentication
- The system will NOT download videos or audio
- The system will NOT implement a custom video player
- The system will NOT handle live streams specially beyond opening the URL
- The system will NOT implement a queue or playlist management on the server side
- The system will NOT control YouTube's internal player controls (seek, quality, subtitles) — only play/pause via keyboard
