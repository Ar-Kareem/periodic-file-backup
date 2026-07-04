from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from src.core import (
    Settings,
    default_settings,
    is_settings_ready,
    load_settings,
    remove_missing_backup_hash_entries,
    save_settings,
    selected_folder_pattern,
    sync_files,
)


ICON_NAME = "periodic-file-backup.ico"
DEFAULT_WINDOW_SIZE = "430x390"
MIN_WINDOW_WIDTH = 380
MIN_WINDOW_HEIGHT = 340


def resource_path(name: str) -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / name
    return Path(__file__).resolve().parents[1] / name


def truncate_to_width(value: str, max_width: int, font: tkfont.Font) -> str:
    value = value.strip()
    if max_width <= 0 or font.measure(value) <= max_width:
        return value

    ellipsis = "..."
    if font.measure(ellipsis) >= max_width:
        return ellipsis

    low = 0
    high = len(value)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = value[:mid] + ellipsis
        if font.measure(candidate) <= max_width:
            low = mid
        else:
            high = mid - 1
    return value[:low] + ellipsis


class Tooltip:
    def __init__(self, widget: tk.Widget, text_getter) -> None:
        self.widget = widget
        self.text_getter = text_getter
        self.tip: tk.Toplevel | None = None
        self.after_id: str | None = None
        widget.bind("<Enter>", self.schedule)
        widget.bind("<Leave>", self.hide)
        widget.bind("<ButtonPress>", self.hide)

    def schedule(self, _event: tk.Event) -> None:
        self.cancel()
        self.after_id = self.widget.after(400, self.show)

    def cancel(self) -> None:
        if self.after_id:
            self.widget.after_cancel(self.after_id)
            self.after_id = None

    def show(self) -> None:
        text = str(self.text_getter()).strip()
        if not text:
            return
        self.hide()
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        label = ttk.Label(
            self.tip,
            text=text,
            padding=(8, 4),
            relief=tk.SOLID,
            borderwidth=1,
            wraplength=520,
        )
        label.pack()

    def hide(self, _event: tk.Event | None = None) -> None:
        self.cancel()
        if self.tip:
            self.tip.destroy()
            self.tip = None


class PeriodicFileBackupApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Periodic File Backup")
        self.set_window_icon(self.root)
        self.root.geometry(DEFAULT_WINDOW_SIZE)
        self.root.minsize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        self.settings = load_settings()
        self.last_period_started_at: datetime | None = None
        self.sync_running = False
        self.sync_after_id: str | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.tracked_var = tk.StringVar()
        self.destination_var = tk.StringVar()
        self.size_limit_var = tk.StringVar()
        self.period_var = tk.StringVar()
        self.full_tracked_value = ""
        self.full_destination_value = ""
        self.info_container: ttk.Frame | None = None
        self.tracked_label: ttk.Label | None = None
        self.destination_label: ttk.Label | None = None

        self.build_main_window()
        self.refresh_info()
        self.root.after(100, self.drain_log_queue)

        if is_settings_ready(self.settings):
            remove_missing_backup_hash_entries(self.settings.destination)
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
        self.info_container = container
        container.pack(fill=tk.BOTH, expand=True)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(5, weight=1)
        container.bind("<Configure>", self.update_display_values)

        ttk.Label(container, text="Tracked").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.tracked_label = ttk.Label(container, textvariable=self.tracked_var)
        self.tracked_label.grid(
            row=0, column=1, sticky=tk.EW, pady=2
        )
        self.tracked_label.bind("<Configure>", self.update_display_values)
        Tooltip(self.tracked_label, lambda: self.full_tracked_value)

        ttk.Label(container, text="Destination").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.destination_label = ttk.Label(container, textvariable=self.destination_var)
        self.destination_label.grid(
            row=1, column=1, sticky=tk.EW, pady=2
        )
        self.destination_label.bind("<Configure>", self.update_display_values)
        Tooltip(self.destination_label, lambda: self.full_destination_value)

        ttk.Label(container, text="Size Limit").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Label(container, textvariable=self.size_limit_var).grid(
            row=2, column=1, sticky=tk.EW, pady=2
        )

        ttk.Label(container, text="Period").grid(row=3, column=0, sticky=tk.W, pady=2)
        ttk.Label(container, textvariable=self.period_var).grid(
            row=3, column=1, sticky=tk.EW, pady=2
        )

        actions = ttk.Frame(container)
        actions.grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
        ttk.Button(actions, text="Setup", command=self.open_setup).pack(
            side=tk.LEFT,
            padx=(0, 8),
        )
        ttk.Button(actions, text="Sync Now", command=self.sync_now).pack(side=tk.LEFT)

        self.log_box = scrolledtext.ScrolledText(
            container,
            height=15,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.log_box.grid(row=5, column=0, columnspan=2, sticky=tk.NSEW, pady=(12, 0))

    def refresh_info(self) -> None:
        if not is_settings_ready(self.settings):
            self.full_tracked_value = "Not initialized"
            self.full_destination_value = "Not initialized"
            self.size_limit_var.set("Not initialized")
            self.period_var.set("Not initialized")
            self.update_display_values()
            return

        size_limit = (
            "No limit"
            if self.settings.size_limit_mb == 0
            else f"{self.settings.size_limit_mb:g} MB"
        )
        self.full_tracked_value = self.settings.tracked
        self.full_destination_value = self.settings.destination
        self.size_limit_var.set(size_limit)
        self.period_var.set(f"{self.settings.period_minutes:g} minutes")
        self.update_display_values()

    def update_display_values(self, _event: tk.Event | None = None) -> None:
        for label, variable, full_value in (
            (self.tracked_label, self.tracked_var, self.full_tracked_value),
            (self.destination_label, self.destination_var, self.full_destination_value),
        ):
            if label is None:
                variable.set(full_value)
                continue

            font = tkfont.Font(font=label.cget("font"))
            available_width = self.available_value_width(label)
            variable.set(truncate_to_width(full_value, available_width, font))

    def available_value_width(self, label: ttk.Label) -> int:
        if self.info_container is None:
            return label.winfo_width()

        self.info_container.update_idletasks()
        container_width = self.info_container.winfo_width()
        label_x = label.winfo_x()
        padding = 12
        scaling = float(self.root.tk.call("tk", "scaling"))
        available_width = max(label.winfo_width(), container_width - label_x - padding)
        return int((available_width * scaling) - tkfont.Font(font=label.cget("font")).measure("..."))

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

    def schedule_sync(self, delay_ms: int | None = None, manual: bool = False) -> None:
        if self.sync_after_id:
            self.root.after_cancel(self.sync_after_id)
            self.sync_after_id = None

        if delay_ms is None:
            delay_ms = int(self.settings.period_minutes * 60 * 1000)

        self.sync_after_id = self.root.after(
            delay_ms,
            lambda: self.start_sync(manual=manual),
        )

    def sync_now(self) -> None:
        if self.sync_running:
            return
        if not is_settings_ready(self.settings):
            self.open_setup()
            return
        self.schedule_sync(0, manual=True)

    def start_sync(self, manual: bool = False) -> None:
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
        if manual:
            self.log("manual sync started")
        else:
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
        self.log("settings saved")
        setup.destroy()
        if not self.sync_running:
            self.schedule_sync(0)


def main() -> None:
    root = tk.Tk()
    PeriodicFileBackupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
