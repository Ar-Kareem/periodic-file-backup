from __future__ import annotations

import json
import os
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from src.core import (
    BackupTarget,
    HASHES_NAME,
    Settings,
    load_hash_entries,
    load_settings,
    remove_missing_backup_hash_entries,
    save_settings,
    selected_folder_pattern,
    sync_files,
)


def write_file(path: Path, content: bytes, modified_at: datetime | None = None) -> None:
    path.write_bytes(content)
    if modified_at:
        timestamp = modified_at.timestamp()
        os.utime(path, (timestamp, timestamp))


class BackupCoreTests(unittest.TestCase):
    def test_first_sync_copies_matching_files_and_records_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            source = tmp_path / "source"
            destination = tmp_path / "destination"
            source.mkdir()
            write_file(source / "Name1.sav", b"one", datetime(2026, 7, 1, 8, 9, 10))
            write_file(source / "Other.sav", b"two")

            settings = Settings(
                targets=[BackupTarget(str(source / "Name*"), str(destination))],
                size_limit_mb=10,
                period_minutes=5,
            )

            result = sync_files(settings, None, datetime(2026, 7, 3, 12, 30, 1))

            self.assertEqual(result.synced_count, 1)
            self.assertEqual(result.errors, [])
            backups = [path.name for path in destination.iterdir() if path.name != HASHES_NAME]
            self.assertEqual(backups, ["2026-07-01--08-09-10--Name1.sav"])

            entries, known_hashes = load_hash_entries(destination)
            self.assertEqual(len(entries), 1)
            self.assertEqual(len(known_hashes), 1)
            self.assertEqual(set(entries[0]), {"hash", "original", "backup", "copied_at"})

    def test_dedupes_by_file_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            source = tmp_path / "source"
            destination = tmp_path / "destination"
            source.mkdir()
            write_file(source / "Name1.sav", b"same")
            write_file(source / "Name2.sav", b"same")

            settings = Settings(
                targets=[BackupTarget(str(source / "Name*"), str(destination))],
                size_limit_mb=10,
                period_minutes=5,
            )

            result = sync_files(settings, None, datetime(2026, 7, 3, 12, 30, 1))

            self.assertEqual(result.synced_count, 1)
            entries = json.loads((destination / HASHES_NAME).read_text(encoding="utf-8"))
            self.assertEqual(len(entries), 1)

    def test_only_files_newer_than_last_period_are_considered(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            source = tmp_path / "source"
            destination = tmp_path / "destination"
            source.mkdir()
            previous_period = datetime(2026, 7, 3, 12, 30, 1)
            write_file(source / "Name_old.sav", b"old", previous_period - timedelta(seconds=1))
            new_mtime = previous_period + timedelta(seconds=1)
            write_file(source / "Name_new.sav", b"new", new_mtime)

            settings = Settings(
                targets=[BackupTarget(str(source / "Name*"), str(destination))],
                size_limit_mb=10,
                period_minutes=5,
            )

            result = sync_files(settings, previous_period, datetime(2026, 7, 3, 12, 35, 1))

            self.assertEqual(result.synced_count, 1)
            backups = [path.name for path in destination.iterdir() if path.name != HASHES_NAME]
            self.assertEqual(backups, ["2026-07-03--12-30-02--Name_new.sav"])

    def test_file_at_size_limit_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            source = tmp_path / "source"
            destination = tmp_path / "destination"
            source.mkdir()
            write_file(source / "Name_big.sav", b"x" * 1024)

            settings = Settings(
                targets=[BackupTarget(str(source / "Name*"), str(destination))],
                size_limit_mb=1024 / (1024 * 1024),
                period_minutes=5,
            )

            result = sync_files(settings, None, datetime(2026, 7, 3, 12, 30, 1))

            self.assertEqual(result.synced_count, 0)
            self.assertEqual(len(result.errors), 1)
            self.assertIn("hit the 0.000976562 MB limit; skipped", result.errors[0])

    def test_removes_hash_entries_for_missing_backup_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            existing_backup = destination / "existing.sav"
            missing_backup = destination / "missing.sav"
            existing_backup.write_bytes(b"existing")
            hash_entries = [
                {
                    "hash": "existing_hash",
                    "original": "C:/source/existing.sav",
                    "backup": str(existing_backup),
                    "copied_at": "2026-07-03T12:30:01",
                },
                {
                    "hash": "missing_hash",
                    "original": "C:/source/missing.sav",
                    "backup": str(missing_backup),
                    "copied_at": "2026-07-03T12:30:02",
                },
            ]
            (destination / HASHES_NAME).write_text(
                json.dumps(hash_entries, indent=2),
                encoding="utf-8",
            )

            removed_count = remove_missing_backup_hash_entries(destination)

            self.assertEqual(removed_count, 1)
            entries = json.loads((destination / HASHES_NAME).read_text(encoding="utf-8"))
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["hash"], "existing_hash")

    def test_selected_folder_pattern_uses_folder_contents_only(self) -> None:
        self.assertEqual(selected_folder_pattern("C:/Saves"), str(Path("C:/Saves") / "*"))

    def test_syncs_multiple_targets_to_their_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            source1 = tmp_path / "source1"
            source2 = tmp_path / "source2"
            destination1 = tmp_path / "destination1"
            destination2 = tmp_path / "destination2"
            source1.mkdir()
            source2.mkdir()
            write_file(source1 / "A.sav", b"one", datetime(2026, 7, 1, 8, 9, 10))
            write_file(source2 / "C.sav", b"two", datetime(2026, 7, 2, 8, 9, 10))

            settings = Settings(
                targets=[
                    BackupTarget(str(source1 / "*"), str(destination1)),
                    BackupTarget(str(source2 / "*"), str(destination2)),
                ],
                size_limit_mb=10,
                period_minutes=5,
            )

            result = sync_files(settings, None, datetime(2026, 7, 3, 12, 30, 1))

            self.assertEqual(result.synced_count, 2)
            backups1 = [path.name for path in destination1.iterdir() if path.name != HASHES_NAME]
            backups2 = [path.name for path in destination2.iterdir() if path.name != HASHES_NAME]
            self.assertEqual(backups1, ["2026-07-01--08-09-10--A.sav"])
            self.assertEqual(backups2, ["2026-07-02--08-09-10--C.sav"])

    def test_directory_target_is_zipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            source = tmp_path / "source"
            destination = tmp_path / "destination"
            folder = source / "FolderA"
            nested = folder / "nested"
            nested.mkdir(parents=True)
            write_file(nested / "save.txt", b"folder save", datetime(2026, 7, 1, 8, 9, 10))

            settings = Settings(
                targets=[BackupTarget(str(source / "*"), str(destination))],
                size_limit_mb=10,
                period_minutes=5,
            )

            result = sync_files(settings, None, datetime(2026, 7, 3, 12, 30, 1))

            self.assertEqual(result.synced_count, 1)
            backups = [path for path in destination.iterdir() if path.name != HASHES_NAME]
            self.assertEqual([path.name for path in backups], ["2026-07-01--08-09-10--FolderA.zip"])
            with zipfile.ZipFile(backups[0]) as archive:
                self.assertEqual(archive.namelist(), ["nested/save.txt"])
                self.assertEqual(archive.read("nested/save.txt"), b"folder save")

    def test_settings_save_and_load_targets_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base_dir = Path(temp)
            settings = Settings(
                targets=[
                    BackupTarget("C:/src1/*", "D:/dest1"),
                    BackupTarget("C:/src2/*", "D:/dest2"),
                ],
                size_limit_mb=7,
                period_minutes=3,
            )

            save_settings(settings, base_dir)
            loaded = load_settings(base_dir)

            self.assertEqual(loaded.targets, settings.targets)
            self.assertEqual(loaded.size_limit_mb, 7)
            self.assertEqual(loaded.period_minutes, 3)
            data = json.loads((base_dir / "periodic-file-backup.settings").read_text())
            self.assertEqual(set(data), {"targets", "size_limit_mb", "period_minutes"})


if __name__ == "__main__":
    unittest.main()
