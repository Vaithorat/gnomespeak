# Agent Autonomy

## Purpose
Define the system-wide autonomy behaviors that enable the AI agent to execute complex tasks completely — from voice command to completed action — without requiring user intervention. These rules apply across ALL tools and capabilities.

## Requirements

### Requirement: Full PC Control (Integration)
The system SHALL execute tasks completely without user intervention.
#### Scenario: Autonomous Execution
- GIVEN the user says "open firefox, go to youtube and search golmaal 3 and play the first video"
- WHEN the LLM processes this multi-step request
- THEN the LLM SHALL decompose it into: yt_play("golmaal 3") → media_control("play_pause")
- AND SHALL NOT ask the user to click, tap, or do anything
- AND SHALL execute all steps automatically
- AND SHALL report the final result

#### Scenario: No User Guidance
- GIVEN a task is within the agent's capabilities
- WHEN the LLM processes it
- THEN the LLM SHALL NOT respond with "click on the video" or "you can now..."
- AND SHALL use its tools to accomplish the task
- AND SHALL only inform the user of what was done

### Requirement: English-Only Responses (Integration)
The system SHALL always respond in English.
#### Scenario: Non-English User Input
- GIVEN the user speaks in any language (Hindi, Chinese, Spanish, etc.)
- WHEN the LLM generates a response
- THEN the response SHALL be in English
- AND the LLM SHALL execute the requested task regardless of input language

### Requirement: Error Recovery Protocol (Integration)
The system SHALL recover from tool failures autonomously.
#### Scenario: Tool Failure Recovery
- GIVEN a tool call returns `{"success": false, "message": "..."}`
- WHEN the LLM receives the error
- THEN the LLM SHALL analyze the error message
- AND SHALL try an alternative approach before giving up
- AND SHALL inform the user only if no alternative exists

#### Scenario: YouTube Playback Failure
- GIVEN `yt_play` returns `fallback: true` (could not autoplay)
- WHEN the LLM sees the fallback result
- THEN the LLM SHALL call `media_control(action='play_pause')` to try starting playback
- AND SHALL NOT open the same URL again

#### Scenario: App Not Found
- GIVEN `open_app` returns "Could not open {name}"
- WHEN the LLM receives the error
- THEN the LLM SHALL try alternative names (e.g., "chrome" → "google chrome" → "browser")
- AND SHALL inform the user if no alternative works

### Requirement: Task Decomposition (Integration)
The system SHALL break complex tasks into executable steps.
#### Scenario: Multi-Step Decomposition
- GIVEN the user says "turn on bluetooth, connect to my speaker, and play music"
- WHEN the LLM processes this
- THEN the LLM SHALL decompose into: control_bluetooth("on") → control_bluetooth("connect", "speaker") → play_media("music")
- AND SHALL execute each step sequentially
- AND SHALL verify each step's result before proceeding

#### Scenario: Conditional Execution
- GIVEN a task depends on a previous step's result
- WHEN the first step fails
- THEN the LLM SHALL NOT proceed to dependent steps
- AND SHALL inform the user of the failure and what was attempted

### Requirement: State Verification (Integration)
The system SHALL verify outcomes where possible.
#### Scenario: Post-Action Verification
- GIVEN a tool has been executed
- WHEN the tool returns a result
- THEN the LLM SHALL interpret the result to determine if the action succeeded
- AND SHALL take corrective action if the result indicates failure

#### Scenario: Honest Status Reporting
- GIVEN a tool's result is uncertain (e.g., media_control returns "Toggled play/pause")
- WHEN the LLM reports to the user
- THEN the LLM SHALL say what was attempted, not claim success it cannot verify
- AND SHALL NOT say "video is now playing" when it only pressed Space

### Requirement: Self-Correction (Integration)
The system SHALL correct mistakes without user prompting.
#### Scenario: Wrong Tool Selected
- GIVEN the LLM called `yt_search` when it should have called `yt_play`
- WHEN the result shows search results instead of a playing video
- THEN the LLM SHALL recognize the mistake
- AND SHALL call `media_control(action='play_pause')` to try starting playback
- AND SHALL NOT open the search URL again

#### Scenario: Context Loss Recovery
- GIVEN the user says "play the first video" but the LLM doesn't know what was searched
- WHEN the LLM cannot determine the context
- THEN the LLM SHALL ask the user what they want to play
- AND SHALL NOT guess or open random content

### Requirement: Concise Responses (Integration)
The system SHALL provide brief, natural responses.
#### Scenario: Task Completion
- GIVEN a task has been completed
- WHEN the LLM generates a response
- THEN the response SHALL be 1-2 sentences maximum
- AND SHALL describe what was done, not how

#### Scenario: In-Progress Tasks
- GIVEN a multi-step task is in progress
- WHEN the LLM reports status
- THEN the response SHALL be minimal (e.g., "Done." or "Playing Golmaal 3 on YouTube.")

### Requirement: Tool Chaining Intelligence (Integration)
The system SHALL chain tools intelligently based on the task.
#### Scenario: YouTube Chain
- GIVEN the user wants to play a YouTube video
- WHEN the LLM processes this
- THEN the LLM SHALL call `yt_play` (which opens the video)
- AND SHALL follow up with `media_control(action='play_pause')` to ensure playback
- AND SHALL NOT call `browser_navigate` or `yt_search` separately

#### Scenario: File Operations Chain
- GIVEN the user says "copy all files from Downloads to Documents"
- WHEN the LLM processes this
- THEN the LLM SHALL call `list_dir` to see Downloads contents
- AND SHALL call `copy` for each file
- AND SHALL report the total files copied

### Non-Goals
- The system will NOT implement visual testing (screenshots, DOM inspection)
- The system will NOT control the mouse pointer or perform clicks
- The system will NOT manage browser tabs beyond opening URLs
- The system will NOT implement a planning/reasoning engine beyond the LLM's native capabilities
