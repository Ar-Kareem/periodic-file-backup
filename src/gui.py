from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from src.core import (
    Settings,
    default_settings,
    is_settings_ready,
    load_settings,
    save_settings,
    selected_folder_pattern,
    sync_files,
)


ICON_NAME = "periodic-file-backup.ico"


def resource_path(name: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / name
    return Path(__file__).resolve().parents[1] / name


class PeriodicFileBackupApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Periodic File Backup")
        self.set_window_icon(self.root)
        self.root.minsize(720, 460)

        self.settings = load_settings()
        self.last_period_started_at: datetime | None = None
        self.sync_running = False
        self.sync_after_id: str | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.tracked_var = tk.StringVar()
        self.destination_var = tk.StringVar()
        self.size_limit_var = tk.StringVar()
        self.period_var = tk.StringVar()
        self.next_sync_var = tk.StringVar(value="Not scheduled")

        self.build_main_window()
        self.refresh_info()
        self.root.after(100, self.drain_log_queue)

        if is_settings_ready(self.settings):
            self.schedule_sync(0)
        else:
            self.root.after(100, self.open_setup)

    def set_window_icon(self, window: tk.Tk | tk.Toplevel) -> None:
        icon_path = resource_path(ICON_NAME)
        if not icon_path.exists():
            return
        try:
            window.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    def build_main_window(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(5, weight=1)

        ttk.Label(container, text="Tracked").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Label(container, textvariable=self.tracked_var).grid(
            row=0, column=1, sticky=tk.EW, pady=2
        )

        ttk.Label(container, text="Destination").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Label(container, textvariable=self.destination_var).grid(
            row=1, column=1, sticky=tk.EW, pady=2
        )

        ttk.Label(container, text="Size Limit").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Label(container, textvariable=self.size_limit_var).grid(
            row=2, column=1, sticky=tk.EW, pady=2
        )

        ttk.Label(container, text="Period").grid(row=3, column=0, sticky=tk.W, pady=2)
        ttk.Label(container, textvariable=self.period_var).grid(
            row=3, column=1, sticky=tk.EW, pady=2
        )

        ttk.Label(container, text="Next Sync").grid(row=4, column=0, sticky=tk.W, pady=2)
        ttk.Label(container, textvariable=self.next_sync_var).grid(
            row=4, column=1, sticky=tk.EW, pady=2
        )

        actions = ttk.Frame(container)
        actions.grid(row=0, column=2, rowspan=5, sticky=tk.NE, padx=(12, 0))
        ttk.Button(actions, text="Setup", command=self.open_setup).pack(fill=tk.X, pady=(0, 6))
        ttk.Button(actions, text="Sync Now", command=self.sync_now).pack(fill=tk.X)

        self.log_box = scrolledtext.ScrolledText(
            container,
            height=15,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.log_box.grid(row=5, column=0, columnspan=3, sticky=tk.NSEW, pady=(12, 0))

    def refresh_info(self) -> None:
        if not is_settings_ready(self.settings):
            self.tracked_var.set("Not initialized")
            self.destination_var.set("Not initialized")
            self.size_limit_var.set("Not initialized")
            self.period_var.set("Not initialized")
            return

        size_limit = (
            "No limit"
            if self.settings.size_limit_mb == 0
            else f"{self.settings.size_limit_mb:g} MB"
        )
        self.tracked_var.set(self.settings.tracked)
        self.destination_var.set(self.settings.destination)
        self.size_limit_var.set(size_limit)
        self.period_var.set(f"{self.settings.period_minutes:g} minutes")

    def timestamp(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, message: str) -> None:
        self.log_queue.put(f"[{self.timestamp()}] {message}")

    def drain_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if message == "__sync_finished__":
                self.finish_sync()
                continue
            self.log_box.configure(state=tk.NORMAL)
            self.log_box.insert(tk.END, message + "\n")
            self.log_box.configure(state=tk.DISABLED)
            self.log_box.see(tk.END)
        self.root.after(100, self.drain_log_queue)

    def schedule_sync(self, delay_ms: int | None = None) -> None:
        if self.sync_after_id:
            self.root.after_cancel(self.sync_after_id)
            self.sync_after_id = None

        if delay_ms is None:
            delay_ms = int(self.settings.period_minutes * 60 * 1000)

        next_sync = datetime.now()
        if delay_ms:
            next_sync = datetime.fromtimestamp(
                datetime.now().timestamp() + delay_ms / 1000
            )
        self.next_sync_var.set(next_sync.strftime("%Y-%m-%d %H:%M:%S"))
        self.sync_after_id = self.root.after(delay_ms, self.start_sync)

    def sync_now(self) -> None:
        if self.sync_running:
            return
        if not is_settings_ready(self.settings):
            self.open_setup()
            return
        self.schedule_sync(0)

    def start_sync(self) -> None:
        if self.sync_running:
            return
        if not is_settings_ready(self.settings):
            self.open_setup()
            return

        self.sync_after_id = None
        self.sync_running = True
        period_started_at = datetime.now()
        previous_period_started_at = self.last_period_started_at
        self.last_period_started_at = period_started_at
        self.log("sync started")

        thread = threading.Thread(
            target=self.run_sync,
            args=(previous_period_started_at,),
            daemon=True,
        )
        thread.start()

    def run_sync(self, previous_period_started_at: datetime | None) -> None:
        try:
            result = sync_files(self.settings, previous_period_started_at)
            for error in result.errors or []:
                self.log(error)
            self.log(
                f"{result.synced_count} new files synced. "
                f"Next sync in {self.settings.period_minutes:g} minutes"
            )
        finally:
            self.log_queue.put("__sync_finished__")

    def finish_sync(self) -> None:
        self.sync_running = False
        self.schedule_sync()

    def open_setup(self) -> None:
        setup = tk.Toplevel(self.root)
        setup.title("Setup")
        self.set_window_icon(setup)
        setup.transient(self.root)
        setup.grab_set()
        setup.minsize(640, 190)

        current = self.settings if is_settings_ready(self.settings) else default_settings()
        tracked = tk.StringVar(value=current.tracked)
        destination = tk.StringVar(value=current.destination)
        size_limit = tk.StringVar(value=f"{current.size_limit_mb:g}")
        period = tk.StringVar(value=f"{current.period_minutes:g}")

        frame = ttk.Frame(setup, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Tracked").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=tracked).grid(row=0, column=1, sticky=tk.EW, pady=4)
        ttk.Button(
            frame,
            text="Select Folder",
            command=lambda: self.choose_tracked_folder(tracked),
        ).grid(row=0, column=2, padx=(8, 0), pady=4)

        ttk.Label(frame, text="Destination").grid(row=1, column=0, sticky=tk.W, pady=4)
        ttk.Entry(frame, textvariable=destination).grid(
            row=1, column=1, sticky=tk.EW, pady=4
        )
        ttk.Button(
            frame,
            text="Select Folder",
            command=lambda: self.choose_destination_folder(destination),
        ).grid(row=1, column=2, padx=(8, 0), pady=4)

        ttk.Label(frame, text="Size Limit").grid(row=2, column=0, sticky=tk.W, pady=4)
        size_row = ttk.Frame(frame)
        size_row.grid(row=2, column=1, sticky=tk.W, pady=4)
        ttk.Entry(size_row, textvariable=size_limit, width=10).pack(side=tk.LEFT)
        ttk.Label(size_row, text=" MB").pack(side=tk.LEFT)

        ttk.Label(frame, text="Period").grid(row=3, column=0, sticky=tk.W, pady=4)
        period_row = ttk.Frame(frame)
        period_row.grid(row=3, column=1, sticky=tk.W, pady=4)
        ttk.Entry(period_row, textvariable=period, width=10).pack(side=tk.LEFT)
        ttk.Label(period_row, text=" minutes").pack(side=tk.LEFT)

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky=tk.E, pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=setup.destroy).pack(
            side=tk.RIGHT, padx=(8, 0)
        )
        ttk.Button(
            buttons,
            text="Save",
            command=lambda: self.save_setup(
                setup,
                tracked.get(),
                destination.get(),
                size_limit.get(),
                period.get(),
            ),
        ).pack(side=tk.RIGHT)

    def choose_tracked_folder(self, tracked: tk.StringVar) -> None:
        folder = filedialog.askdirectory(parent=self.root)
        if folder:
            tracked.set(selected_folder_pattern(folder))

    def choose_destination_folder(self, destination: tk.StringVar) -> None:
        folder = filedialog.askdirectory(parent=self.root)
        if folder:
            destination.set(str(Path(folder)))

    def save_setup(
        self,
        setup: tk.Toplevel,
        tracked: str,
        destination: str,
        size_limit: str,
        period: str,
    ) -> None:
        try:
            parsed_size_limit = float(size_limit)
            parsed_period = float(period)
        except ValueError:
            messagebox.showerror("Invalid setup", "Size limit and period must be numbers.")
            return

        if not tracked.strip():
            messagebox.showerror("Invalid setup", "Tracked is required.")
            return
        if not destination.strip():
            messagebox.showerror("Invalid setup", "Destination is required.")
            return
        if parsed_size_limit < 0:
            messagebox.showerror("Invalid setup", "Size limit cannot be negative.")
            return
        if parsed_period <= 0:
            messagebox.showerror("Invalid setup", "Period must be greater than 0.")
            return

        self.settings = Settings(
            tracked=tracked.strip(),
            destination=destination.strip(),
            size_limit_mb=parsed_size_limit,
            period_minutes=parsed_period,
        )
        save_settings(self.settings)
        self.refresh_info()
        setup.destroy()
        if not self.sync_running:
            self.schedule_sync(0)


def main() -> None:
    root = tk.Tk()
    PeriodicFileBackupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
