# Periodic File Backup

`periodic-file-backup` is a small Windows GUI app for periodically backing up tiny files.

It watches files matched by a glob pattern, copies new file contents into a destination folder, and avoids duplicate backups by hashing file contents. It is built with Python `tkinter`.

## Quick Start

Run:

```text
dist\periodic-file-backup.exe
```

On first launch, the setup window asks for:

- `Tracked`: a glob pattern for files to back up, such as `C:\SomeFolder\prefix*`.
- `Destination`: the folder where backups should be placed.
- `Size Limit`: max file size in MB. Use `0` for no limit.
- `Period`: minutes between checks.

The app syncs immediately after setup, then repeats on the configured period. Use `Sync Now` to manually run a sync.

## Files

- `periodic-file-backup.settings` is stored beside the exe.
- `periodic-file-backup.hashes` is stored in the destination folder.
- Backups are named `YYYY-MM-DD-HH-MM-SS-originalname`, using the original file's modified time.

## Build

Make an environment `./env/` with Python 3.11 and pyinstaller:

```powershell
conda activate ./env/
.\env\python.exe -m unittest -v
.\env\Scripts\pyinstaller.exe --clean periodic-file-backup.spec
```

The built executable is created at:

```text
dist\periodic-file-backup.exe
```
