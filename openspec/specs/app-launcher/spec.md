# Application Launcher

## Purpose
Find and launch applications on the Windows PC using voice commands.

## Requirements

### Requirement: App Discovery Priority
The system SHALL search for applications in a defined priority order.
#### Scenario: Search Order
- GIVEN the user says "open <appname>"
- WHEN the system needs to find the application
- THEN the system SHALL search in this order:
  1. Start Menu Programs directories (both `ProgramData` and `AppData`)
  2. Common install directories: `C:\Program Files`, `C:\Program Files (x86)`, `%LOCALAPPDATA%\Programs`
  3. System `PATH` environment variable directories
  4. Windows `start` command as last resort

### Requirement: Start Menu Search
The system SHALL search Start Menu shortcuts and executables.
#### Scenario: Find by Name
- GIVEN an app name like "chrome"
- WHEN the system searches Start Menu directories
- THEN it SHALL recursively search for `*.lnk` and `*.exe` files
- AND SHALL match if the app name is a substring (case-insensitive) of the filename's stem
- AND SHALL return the first match found

### Requirement: PATH Search
The system SHALL search system PATH for executables.
#### Scenario: Find in PATH
- GIVEN an app name
- WHEN the system iterates PATH directories
- THEN it SHALL check each directory for the app name with each PATHEXT extension (`.COM`, `.EXE`, `.BAT`, `.CMD`)
- AND SHALL return the first match found

### Requirement: Application Launch
The system SHALL launch the found application.
#### Scenario: Launch by Full Path
- GIVEN an executable path was discovered
- WHEN launching
- THEN the system SHALL use `subprocess.Popen` with the full path as argument list
- AND SHALL return success with "Opened {name}"

### Requirement: Windows Start Fallback
The system SHALL attempt the Windows `start` command as a last resort.
#### Scenario: Fallback Launch
- GIVEN no executable path was found through search
- WHEN launching
- THEN the system SHALL run `cmd /c start "" "{name}"`
- AND SHALL return success with "Attempted to open {name}"

### Requirement: Launch Failure
The system SHALL report failures gracefully.
#### Scenario: App Not Found
- GIVEN the app cannot be found in any search location
- AND the Windows `start` command also fails
- WHEN the launch result is returned
- THEN the system SHALL return failure with "Could not open {name}: {error}"
