# Periodic File Backup

`periodic-file-backup` is a small Windows GUI app for periodically copying tiny tracked files into a backup folder.

The app watches files matched by a glob pattern, periodically checks for files modified since the previous in-memory period, and copies new file contents to a destination folder. It deduplicates backups by SHA-256 file-content hash, not by filename.

It is written in Python with `tkinter` and can be packaged as a single `.exe` with PyInstaller.

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
- Next Sync

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

The main window also has:

- `Setup` button.
- `Sync Now` button.
- scrolling log textbox that always scrolls to the bottom.

## Sync Behavior

On startup:

1. Load settings from `periodic-file-backup.settings`.
2. If settings are invalid or missing, open setup.
3. If settings are valid, sync immediately.
4. Schedule the next sync using `period_minutes`.

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
- `x new files synced. Next sync in y minutes`
- errors

Size limit errors include the file path, actual file size, configured MB limit, and `skipped`.

## Build

Use the bundled environment:

```powershell
.\env\python.exe -m unittest -v
.\env\Scripts\pyinstaller.exe periodic-file-backup.spec
```

The built executable is created at:

```text
dist\periodic-file-backup.exe
```
