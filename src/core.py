from __future__ import annotations

import glob
import hashlib
import json
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


APP_NAME = "periodic-file-backup"
SETTINGS_NAME = f"{APP_NAME}.settings"
HASHES_NAME = f"{APP_NAME}.hashes"
DEFAULT_SIZE_LIMIT_MB = 10
DEFAULT_PERIOD_MINUTES = 5


@dataclass
class BackupTarget:
    tracked: str = ""
    destination: str = ""


@dataclass
class Settings:
    targets: list[BackupTarget] = field(default_factory=list)
    size_limit_mb: float = DEFAULT_SIZE_LIMIT_MB
    period_minutes: float = DEFAULT_PERIOD_MINUTES


@dataclass
class SyncResult:
    synced_count: int = 0
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def settings_path(base_dir: Path | None = None) -> Path:
    return (base_dir or app_dir()) / SETTINGS_NAME


def hashes_path(destination: str | Path) -> Path:
    return Path(destination).expanduser().resolve() / HASHES_NAME


def default_settings(base_dir: Path | None = None) -> Settings:
    directory = base_dir or app_dir()
    return Settings(targets=[BackupTarget(destination=str(directory))])


def backup_targets(settings: Settings) -> list[BackupTarget]:
    return [
        BackupTarget(str(target.tracked), str(target.destination))
        for target in settings.targets
    ]


def load_settings(base_dir: Path | None = None) -> Settings:
    path = settings_path(base_dir)
    if not path.exists():
        return default_settings(base_dir)

    data = json.loads(path.read_text(encoding="utf-8"))
    target_data = data.get("targets", [])
    targets = []
    if isinstance(target_data, list):
        for item in target_data:
            if not isinstance(item, dict):
                continue
            targets.append(
                BackupTarget(
                    tracked=str(item.get("tracked", "")),
                    destination=str(item.get("destination", "")),
                )
            )

    return Settings(
        targets=targets,
        size_limit_mb=float(data.get("size_limit_mb", DEFAULT_SIZE_LIMIT_MB)),
        period_minutes=float(data.get("period_minutes", DEFAULT_PERIOD_MINUTES)),
    )


def save_settings(settings: Settings, base_dir: Path | None = None) -> None:
    path = settings_path(base_dir)
    targets = backup_targets(settings)
    data = {
        "targets": [
            {
                "tracked": target.tracked,
                "destination": target.destination,
            }
            for target in targets
        ],
        "size_limit_mb": settings.size_limit_mb,
        "period_minutes": settings.period_minutes,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_settings_ready(settings: Settings) -> bool:
    targets = backup_targets(settings)
    return bool(targets) and all(
        target.tracked.strip() and target.destination.strip() for target in targets
    )


def load_hash_entries(destination: str | Path) -> tuple[list[dict[str, str]], set[str]]:
    path = hashes_path(destination)
    if not path.exists():
        return [], set()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = []

    if not isinstance(data, list):
        data = []

    entries = [entry for entry in data if isinstance(entry, dict)]
    known_hashes = {str(entry["hash"]) for entry in entries if entry.get("hash")}
    return entries, known_hashes


def write_hash_entries(destination: str | Path, entries: list[dict[str, str]]) -> None:
    path = hashes_path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def remove_missing_backup_hash_entries(destination: str | Path) -> int:
    entries, _known_hashes = load_hash_entries(destination)
    kept_entries = []

    for entry in entries:
        backup_path = entry.get("backup")
        if backup_path and Path(backup_path).exists():
            kept_entries.append(entry)

    removed_count = len(entries) - len(kept_entries)
    if removed_count:
        write_hash_entries(destination, kept_entries)
    return removed_count


def remove_missing_backup_hash_entries_for_settings(settings: Settings) -> int:
    removed_count = 0
    seen_destinations = set()
    for target in backup_targets(settings):
        destination = str(Path(target.destination).expanduser().resolve())
        if destination in seen_destinations:
            continue
        seen_destinations.add(destination)
        removed_count += remove_missing_backup_hash_entries(destination)
    return removed_count


def resolve_tracked_items(pattern: str) -> list[Path]:
    paths = [Path(item) for item in glob.glob(pattern)]
    return sorted(path for path in paths if path.is_file() or path.is_dir())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_directory_files(path: Path) -> list[Path]:
    return sorted(child for child in path.rglob("*") if child.is_file())


def sha256_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for child in iter_directory_files(path):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        with child.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def sha256_item(path: Path) -> str:
    if path.is_dir():
        return sha256_directory(path)
    return sha256_file(path)


def timestamp_for_filename(file_mtime: datetime) -> str:
    return file_mtime.strftime("%Y-%m-%d--%H-%M-%S")


def unique_destination_path(
    destination: Path,
    source_name: str,
    file_mtime: datetime,
) -> Path:
    candidate = destination / f"{timestamp_for_filename(file_mtime)}--{source_name}"
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    for index in range(1, 10_000):
        indexed = destination / f"{stem}-{index}{suffix}"
        if not indexed.exists():
            return indexed
    raise RuntimeError(f"Could not create a unique destination name for {source_name}")


def item_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(child.stat().st_size for child in iter_directory_files(path))


def item_modified_at(path: Path) -> datetime:
    if path.is_dir():
        child_timestamps = [child.stat().st_mtime for child in iter_directory_files(path)]
        if child_timestamps:
            return datetime.fromtimestamp(max(child_timestamps))
    return datetime.fromtimestamp(path.stat().st_mtime)


def backup_source_name(source: Path) -> str:
    if source.is_dir():
        return f"{source.name}.zip"
    return source.name


def copy_item(source: Path, backup_path: Path) -> None:
    if source.is_file():
        shutil.copy2(source, backup_path)
        return

    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for child in iter_directory_files(source):
            archive.write(child, child.relative_to(source))


def format_file_size(size_bytes: int) -> str:
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def sync_files(
    settings: Settings,
    last_period_started_at: datetime | None,
    now: datetime | None = None,
) -> SyncResult:
    now = now or datetime.now()
    result = SyncResult()
    size_limit_bytes = 0
    if settings.size_limit_mb > 0:
        size_limit_bytes = int(settings.size_limit_mb * 1024 * 1024)

    for target in backup_targets(settings):
        destination = Path(target.destination).expanduser().resolve()
        destination.mkdir(parents=True, exist_ok=True)

        entries, known_hashes = load_hash_entries(destination)
        candidates = resolve_tracked_items(target.tracked)
        for source in candidates:
            try:
                modified_at = item_modified_at(source)
                if last_period_started_at is not None:
                    if modified_at <= last_period_started_at:
                        continue

                size_bytes = item_size(source)
                if size_limit_bytes and size_bytes >= size_limit_bytes:
                    result.errors.append(
                        f"{source}: file size {format_file_size(size_bytes)} hit the "
                        f"{settings.size_limit_mb:g} MB limit; skipped"
                    )
                    continue

                file_hash = sha256_item(source)
                if file_hash in known_hashes:
                    continue

                backup_path = unique_destination_path(
                    destination,
                    backup_source_name(source),
                    modified_at,
                )
                copy_item(source, backup_path)
                entry = {
                    "hash": file_hash,
                    "original": str(source),
                    "backup": str(backup_path),
                    "copied_at": now.isoformat(timespec="seconds"),
                }
                entries.append(entry)
                known_hashes.add(file_hash)
                result.synced_count += 1
            except Exception as exc:
                result.errors.append(f"{source}: {exc}")

        write_hash_entries(destination, entries)
    return result


def selected_folder_pattern(folder: str | Path) -> str:
    return str(Path(folder) / "*")
