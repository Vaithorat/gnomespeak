# File Operations

## Purpose
Execute file and directory operations on the Windows PC via voice commands — navigate, list, create, delete, copy, and move.

## Requirements

### Requirement: Navigate to Path
The system SHALL open file or folder paths in Windows Explorer.
#### Scenario: Open Existing Folder
- GIVEN a valid directory path
- WHEN a navigate command is executed
- THEN the system SHALL call `os.startfile(path)`
- AND SHALL return success with the resolved path

#### Scenario: Open Existing File
- GIVEN a valid file path
- WHEN a navigate command is executed
- THEN the system SHALL open the file with its default application via `os.startfile`
- AND SHALL return success

#### Scenario: Path Not Found
- GIVEN a path that does not exist on the filesystem
- WHEN a navigate command is executed
- THEN the system SHALL return failure with "Path not found: {path}"

### Requirement: List Directory Contents
The system SHALL display the contents of a directory.
#### Scenario: List Existing Directory
- GIVEN a valid directory path
- WHEN a list_dir command is executed
- THEN the system SHALL enumerate all entries in the directory
- AND SHALL append "/" suffix for subdirectories
- AND SHALL return the listing up to 20 entries

#### Scenario: List Current Directory
- GIVEN no path is specified (default ".")
- WHEN a list_dir command is executed
- THEN the system SHALL resolve to the current working directory
- AND SHALL list its contents

#### Scenario: Path is a File
- GIVEN the path points to a file, not a directory
- WHEN a list_dir command is executed
- THEN the system SHALL return failure with "Not a directory: {path}"

### Requirement: Create File
The system SHALL create new files with optional content.
#### Scenario: Create Text File
- GIVEN a file path and content string
- WHEN the create_file command is executed
- THEN the system SHALL create all parent directories if they do not exist
- AND SHALL write the content to the file
- AND SHALL return success with the created file path

#### Scenario: Create Empty File
- GIVEN a file path with no content
- WHEN the create_file command is executed
- THEN the system SHALL create an empty file
- AND SHALL return success

### Requirement: Create Folder
The system SHALL create new directories.
#### Scenario: Create New Directory
- GIVEN a directory path
- WHEN the create_folder command is executed
- THEN the system SHALL create the directory and any missing parents
- AND SHALL return success

### Requirement: Delete File or Folder
The system SHALL delete files and directories.
#### Scenario: Delete File
- GIVEN a path to an existing file
- WHEN the delete command is executed
- THEN the system SHALL unlink the file
- AND SHALL return success

#### Scenario: Delete Directory Recursively
- GIVEN a path to an existing directory
- WHEN the delete command is executed
- THEN the system SHALL remove the directory and all its contents
- AND SHALL return success

#### Scenario: Delete Nonexistent Path
- GIVEN a path that does not exist
- WHEN the delete command is executed
- THEN the system SHALL return failure with "Path not found"

### Requirement: Copy Files and Directories
The system SHALL copy files and directories.
#### Scenario: Copy File
- GIVEN a source file and a destination path
- WHEN the copy command is executed
- THEN the system SHALL copy the file using `shutil.copy2` (preserving metadata)
- AND SHALL return success

#### Scenario: Copy Directory Tree
- GIVEN a source directory and a destination path
- WHEN the copy command is executed
- THEN the system SHALL copy the entire directory tree using `shutil.copytree`
- AND SHALL return success

### Requirement: Move Files and Directories
The system SHALL move/rename files and directories.
#### Scenario: Move File
- GIVEN a source and destination path
- WHEN the move command is executed
- THEN the system SHALL move the item using `shutil.move`
- AND SHALL return success

### Requirement: Path Resolution
The system SHALL resolve relative and home-directory paths.
#### Scenario: Expand User Directory
- GIVEN a path starting with `~`
- WHEN any file operation resolves the path
- THEN the system SHALL expand `~` to the user's home directory via `Path.expanduser()`
- AND SHALL resolve to an absolute path via `Path.resolve()`
