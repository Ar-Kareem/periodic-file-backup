from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from core import (
    HASHES_NAME,
    Settings,
    load_hash_entries,
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
            write_file(source / "Name1.sav", b"one")
            write_file(source / "Other.sav", b"two")

            settings = Settings(
                tracked=str(source / "Name*"),
                destination=str(destination),
                size_limit_mb=10,
                period_minutes=5,
            )

            result = sync_files(settings, None, datetime(2026, 7, 3, 12, 30, 1))

            self.assertEqual(result.synced_count, 1)
            self.assertEqual(result.errors, [])
            backups = [path.name for path in destination.iterdir() if path.name != HASHES_NAME]
            self.assertEqual(backups, ["2026-07-03-12-30-01-Name1.sav"])

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

            settings = Settings(str(source / "Name*"), str(destination), 10, 5)

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
            write_file(source / "Name_new.sav", b"new", previous_period + timedelta(seconds=1))

            settings = Settings(str(source / "Name*"), str(destination), 10, 5)

            result = sync_files(settings, previous_period, datetime(2026, 7, 3, 12, 35, 1))

            self.assertEqual(result.synced_count, 1)
            backups = [path.name for path in destination.iterdir() if path.name != HASHES_NAME]
            self.assertEqual(backups, ["2026-07-03-12-35-01-Name_new.sav"])

    def test_file_at_size_limit_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            tmp_path = Path(temp)
            source = tmp_path / "source"
            destination = tmp_path / "destination"
            source.mkdir()
            write_file(source / "Name_big.sav", b"x" * 1024)

            settings = Settings(str(source / "Name*"), str(destination), 1024 / (1024 * 1024), 5)

            result = sync_files(settings, None, datetime(2026, 7, 3, 12, 30, 1))

            self.assertEqual(result.synced_count, 0)
            self.assertEqual(len(result.errors), 1)
            self.assertIn("hit the 0.000976562 MB limit; skipped", result.errors[0])

    def test_selected_folder_pattern_uses_folder_contents_only(self) -> None:
        self.assertEqual(selected_folder_pattern("C:/Saves"), str(Path("C:/Saves") / "*"))


if __name__ == "__main__":
    unittest.main()
