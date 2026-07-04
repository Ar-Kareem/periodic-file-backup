# Periodic File Backup Details

This document describes the behavior needed to replicate `periodic-file-backup` exactly.

## Runtime Files

The app uses these files:

- `periodic-file-backup.exe`: packaged app.
- `periodic-file-backup.settings`: JSON settings file stored beside the `.exe`.
- `periodic-file-backup.hashes`: JSON hash list stored inside the configured destination folder.

No last-sync timestamp is saved to disk. The previous period start time exists only in memory while the app is running. When the app starts, the first sync treats all matching tracked files as eligible.

## Settings

Settings are stored as JSON:

```json
{
  "tracked": "",
  "destination": "folder containing the exe by default",
  "size_limit_mb": 10,
  "period_minutes": 5
}
```

Fields:

- `tracked`: required glob pattern, for example `C:\Users\XXX\AppData\FolderA\FolderB\prefix*`.
- `destination`: required backup folder. Defaults to the folder containing the app.
- `size_limit_mb`: number of MB allowed per tracked file. Default is `10`. If `0`, there is no size limit. If a tracked file is at or above the limit, the app logs an error and skips it.
- `period_minutes`: number of minutes between syncs. Default is `5`.

## GUI

The main window shows basic info at the top:

- Tracked
- Destination
- Size Limit
- Period

If settings are missing or incomplete, the fields show `Not initialized` and the setup window opens.

The setup window contains:

- `Tracked` text field with a `Select Folder` button in the same row.
- `Destination` text field with a `Select Folder` button in the same row.
- `Size Limit` numeric field with hardcoded `MB` label.
- `Period` numeric field with hardcoded `minutes` label.

The tracked folder selector sets the tracked pattern to:

```text
selected_folder\*
```

Below the info rows, the main window also has:

- `Setup` button.
- `Sync Now` button.
- scrolling log textbox that always scrolls to the bottom.
- shortened Tracked and Destination values ending in `...` when needed.
- hover tooltips on the Tracked and Destination values showing the full path/pattern.

## Sync Behavior

On startup:

1. Load settings from `periodic-file-backup.settings`.
2. If settings are invalid or missing, open setup.
3. If settings are valid, remove any hash entries whose `backup` file no longer exists.
4. Sync immediately.
5. Schedule the next sync using `period_minutes`.

For each sync:

1. Log `sync started`.
2. Load `periodic-file-backup.hashes` from the destination folder.
3. Store all existing hashes in a Python `set` for O(1) membership checks.
4. Resolve files using the configured glob pattern.
5. Ignore directories.
6. If this is not the first in-memory sync, only consider files whose modified time is newer than the previous period start time.
7. Skip files at or above `size_limit_mb`, unless the limit is `0`.
8. Compute SHA-256 from file contents only.
9. If the hash already exists, skip the file.
10. Otherwise copy the file to the destination folder.
11. Append a hash entry to the hash list.
12. Write the updated hash list back to `periodic-file-backup.hashes`.
13. Log `x new files synced. Next sync in y minutes`.

Backup filenames use this format:

```text
YYYY-MM-DD-HH-MM-SS-originalname
```

The timestamp comes from the original file's modified time, not the time the backup was copied.

If that filename already exists, append a numeric suffix before the extension.

## Hash File Format

`periodic-file-backup.hashes` is a JSON list. New elements are appended to the bottom. Each element has exactly four keys:

```json
[
  {
    "hash": "sha256 content hash",
    "original": "original source path",
    "backup": "backup destination path",
    "copied_at": "ISO timestamp"
  }
]
```

The hash is based on file contents only. The original filename is not part of the hash.

## Logging

Every log line is timestamped.

The app logs only:

- `sync started`
- `manual sync started`
- `settings saved`
- `x new files synced. Next sync in y minutes`
- errors

Size limit errors include the file path, actual file size, configured MB limit, and `skipped`.

## Packaging Notes

The app uses `periodic-file-backup.spec` for PyInstaller builds. The spec explicitly bundles the matching Tcl/Tk files from the local Python environment and uses `periodic-file-backup.ico` as both the exe icon and the tkinter window icon.
