# Scheduled Commands — Planned

## Purpose
Set timers, reminders, and scheduled tasks via voice commands, with the Python server managing the schedule.

## Requirements

### Requirement: Timer Creation
The system SHALL create countdown timers.
#### Scenario: Set Timer
- GIVEN the user says "set a timer for 5 minutes" or "timer 10 seconds"
- WHEN the command is parsed
- THEN the system SHALL start a countdown timer on the server
- AND SHALL return "Timer set for {duration}"
- AND SHALL notify the client when the timer expires

#### Scenario: Timer Expiry
- GIVEN a timer reaches zero
- WHEN the timer fires
- THEN the system SHALL send a notification to the client
- AND SHALL optionally play a sound on the PC

### Requirement: Reminder Creation
The system SHALL create time-based reminders.
#### Scenario: Set Reminder
- GIVEN the user says "remind me to call John in 30 minutes" or "remind me at 3 PM to take a break"
- WHEN the command is parsed
- THEN the system SHALL parse the time expression and message
- AND SHALL schedule the reminder
- AND SHALL confirm with "Reminder set for {time}"

### Requirement: List Active Schedules
The system SHALL list active timers and reminders.
#### Scenario: List
- GIVEN the user says "list timers" or "show my reminders"
- WHEN the command is parsed
- THEN the system SHALL return all active timers and reminders with their remaining time

### Requirement: Cancel Schedule
The system SHALL cancel active timers and reminders.
#### Scenario: Cancel
- GIVEN the user says "cancel timer" or "stop reminder"
- WHEN the command is parsed
- THEN the system SHALL cancel the matching schedule
- AND SHALL confirm cancellation

### Non-Goals
- The system will NOT persist schedules across server restarts
- The system will NOT integrate with Windows Task Scheduler
