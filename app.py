"""
app.py — Tidal Desktop Downloader GUI  (v2 — CSV import + background queue)
"""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk

import customtkinter as ctk

from tidal_client import TidalClient
from downloader import TidalDownloader, TrackInfo
from csv_parser import parse_csv, SongEntry
from queue_manager import DownloadQueue, QueueJob, JobStatus

# ──────────────────────────────────────────────────────────────────────────────
# Palette
# ──────────────────────────────────────────────────────────────────────────────
BG       = "#0A0A0F"
SURFACE  = "#12121A"
CARD     = "#1A1A26"
CARD2    = "#20202E"
ACCENT   = "#00D4FF"
ACCENT2  = "#9B59B6"
TEXT     = "#E8E8F0"
MUTED    = "#666680"
SUCCESS  = "#00E676"
WARNING  = "#FFB300"
DANGER   = "#FF4444"
BORDER   = "#2A2A3E"

FH  = ("Segoe UI", 13, "bold")
FB  = ("Segoe UI", 11)
FS  = ("Segoe UI", 9)
FM  = ("Consolas", 10)
FSB = ("Segoe UI", 10, "bold")

# ──────────────────────────────────────────────────────────────────────────────
# Tiny reusable widgets
# ──────────────────────────────────────────────────────────────────────────────

class SectionLabel(ctk.CTkLabel):
    def __init__(self, master, text, **kw):
        super().__init__(master, text=text.upper(), font=("Segoe UI", 10, "bold"),
                         text_color=MUTED, **kw)

class Divider(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, height=1, fg_color=BORDER, **kw)

class StatusDot(ctk.CTkLabel):
    _C = {
        JobStatus.PENDING:      (WARNING,  "pending"),
        JobStatus.SEARCHING:    (ACCENT,   "searching"),
        JobStatus.DOWNLOADING:  (ACCENT,   "downloading"),
        JobStatus.PROCESSING:   (ACCENT2,  "processing"),
        JobStatus.DONE:         (SUCCESS,  "done"),
        JobStatus.FAILED:       (DANGER,   "failed"),
        JobStatus.SKIPPED:      (MUTED,    "skipped"),
        JobStatus.CANCELLED:    (MUTED,    "cancelled"),
        "idle":        (MUTED,   "idle"),
        "queued":      (WARNING, "queued"),
        "downloading": (ACCENT,  "downloading"),
        "processing":  (ACCENT2, "processing"),
        "done":        (SUCCESS, "done"),
        "failed":      (DANGER,  "failed"),
        "skipped":     (MUTED,   "skipped"),
    }
    def __init__(self, master, **kw):
        super().__init__(master, text="●  idle", font=FS, text_color=MUTED, **kw)

    def set(self, status):
        color, label = self._C.get(status, (MUTED, str(status)))
        self.configure(text=f"●  {label}", text_color=color)


# ──────────────────────────────────────────────────────────────────────────────
# Search-results track row
# ──────────────────────────────────────────────────────────────────────────────

class TrackRow(ctk.CTkFrame):
    def __init__(self, master, track_info: TrackInfo, on_download, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=8,
                         border_width=1, border_color=BORDER, **kw)
        self.track_info = track_info
        self.columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text=f"{track_info.track_number:02d}",
                     font=FM, text_color=MUTED, width=32
                     ).grid(row=0, column=0, padx=(10, 6), pady=8, sticky="w")

        info = ctk.CTkFrame(self, fg_color="transparent")
        info.grid(row=0, column=1, sticky="ew", pady=8)
        ctk.CTkLabel(info, text=track_info.name, font=FH,
                     text_color=TEXT, anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=f"{track_info.artist}  ·  {track_info.album}",
                     font=FS, text_color=MUTED, anchor="w").pack(fill="x")

        m, s = divmod(track_info.duration, 60)
        ctk.CTkLabel(self, text=f"{m}:{s:02d}", font=FM,
                     text_color=MUTED, width=50).grid(row=0, column=2, padx=6)

        self.badge = StatusDot(self)
        self.badge.grid(row=0, column=3, padx=6)

        self.dl_btn = ctk.CTkButton(
            self, text="↓", width=36, height=30,
            fg_color=ACCENT, hover_color="#00A8CC",
            text_color="#000000", font=("Segoe UI", 14, "bold"),
            corner_radius=6, command=lambda: on_download(self),
        )
        self.dl_btn.grid(row=0, column=4, padx=(6, 10), pady=8)

    def set_status(self, status: str):
        self.badge.set(status)
        if status in ("downloading", "processing", "queued"):
            self.dl_btn.configure(state="disabled", fg_color=MUTED)
        elif status == "done":
            self.dl_btn.configure(state="disabled", fg_color=SUCCESS)
        elif status == "failed":
            self.dl_btn.configure(state="normal", fg_color=DANGER)


# ──────────────────────────────────────────────────────────────────────────────
# Queue panel job row
# ──────────────────────────────────────────────────────────────────────────────

class QueueRow(ctk.CTkFrame):
    def __init__(self, master, job: QueueJob, on_cancel, on_retry, **kw):
        super().__init__(master, fg_color=CARD2, corner_radius=8,
                         border_width=1, border_color=BORDER, **kw)
        self.job_id = job.job_id
        self.columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text=f"#{job.job_id}", font=FM,
                     text_color=MUTED, width=54
                     ).grid(row=0, column=0, padx=(10, 4), pady=8, sticky="w")

        lbl_frame = ctk.CTkFrame(self, fg_color="transparent")
        lbl_frame.grid(row=0, column=1, sticky="ew", pady=6)
        self.title_lbl = ctk.CTkLabel(lbl_frame, text=job.label(), font=FH,
                                       text_color=TEXT, anchor="w")
        self.title_lbl.pack(fill="x")
        self.sub_lbl = ctk.CTkLabel(lbl_frame, text="", font=FS,
                                     text_color=MUTED, anchor="w")
        self.sub_lbl.pack(fill="x")

        self.progress = ctk.CTkProgressBar(self, width=80, height=6,
                                            fg_color=SURFACE, progress_color=ACCENT)
        self.progress.set(0)
        self.progress.grid(row=0, column=2, padx=8)

        self.badge = StatusDot(self)
        self.badge.grid(row=0, column=3, padx=4)

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=0, column=4, padx=(4, 10), pady=8)

        self.retry_btn = ctk.CTkButton(
            btn_frame, text="↺", width=28, height=26,
            fg_color=ACCENT2, hover_color="#7D3C98",
            text_color=TEXT, font=("Segoe UI", 13),
            corner_radius=6, command=lambda: on_retry(self.job_id),
        )
        self.retry_btn.pack(side="left", padx=2)

        self.cancel_btn = ctk.CTkButton(
            btn_frame, text="✕", width=28, height=26,
            fg_color="transparent", hover_color=DANGER,
            text_color=MUTED, font=("Segoe UI", 12),
            border_width=1, border_color=BORDER,
            corner_radius=6, command=lambda: on_cancel(self.job_id),
        )
        self.cancel_btn.pack(side="left", padx=2)

        self.update_job(job)

    def update_job(self, job: QueueJob):
        self.badge.set(job.status)
        self.progress.set(job.progress)

        if job.status == JobStatus.FAILED:
            self.sub_lbl.configure(text=job.error or "Failed", text_color=DANGER)
            self.retry_btn.configure(state="normal")
            self.cancel_btn.configure(state="normal")
        elif job.status in (JobStatus.DONE, JobStatus.SKIPPED):
            self.sub_lbl.configure(text="", text_color=MUTED)
            self.retry_btn.configure(state="disabled")
            self.cancel_btn.configure(state="disabled")
        elif job.status == JobStatus.CANCELLED:
            self.sub_lbl.configure(text="cancelled", text_color=MUTED)
            self.retry_btn.configure(state="normal")
            self.cancel_btn.configure(state="disabled")
        elif job.status == JobStatus.PENDING:
            self.sub_lbl.configure(text="waiting…", text_color=MUTED)
            self.retry_btn.configure(state="disabled")
            self.cancel_btn.configure(state="normal")
        else:
            self.sub_lbl.configure(text=f"{int(job.progress * 100)}%", text_color=MUTED)
            self.retry_btn.configure(state="disabled")
            self.cancel_btn.configure(state="disabled")


# ──────────────────────────────────────────────────────────────────────────────
# CSV file card
# ──────────────────────────────────────────────────────────────────────────────

class CsvFileCard(ctk.CTkFrame):
    def __init__(self, master, path: Path, entries: list[SongEntry],
                 on_queue_all, on_remove, **kw):
        super().__init__(master, fg_color=CARD, corner_radius=10,
                         border_width=1, border_color=BORDER, **kw)
        self.columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="📄", font=("Segoe UI", 22)
                     ).grid(row=0, column=0, rowspan=2, padx=(12, 8), pady=10)
        ctk.CTkLabel(self, text=path.name, font=FH, text_color=TEXT, anchor="w"
                     ).grid(row=0, column=1, sticky="w", pady=(10, 0))
        ctk.CTkLabel(self, text=f"{len(entries)} unique tracks",
                     font=FS, text_color=MUTED, anchor="w"
                     ).grid(row=1, column=1, sticky="w", pady=(0, 10))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=0, column=2, rowspan=2, padx=(8, 12), pady=8)

        ctk.CTkButton(btn_frame, text="Queue All", width=90, height=30,
                      fg_color=ACCENT2, hover_color="#7D3C98",
                      text_color=TEXT, font=FSB, corner_radius=7,
                      command=lambda: on_queue_all(entries),
                      ).pack(side="left", padx=4)

        ctk.CTkButton(btn_frame, text="✕", width=30, height=30,
                      fg_color="transparent", hover_color=DANGER,
                      text_color=MUTED, font=FB,
                      border_width=1, border_color=BORDER, corner_radius=7,
                      command=lambda: on_remove(self),
                      ).pack(side="left", padx=2)


# ══════════════════════════════════════════════════════════════════════════════
# Main window
# ══════════════════════════════════════════════════════════════════════════════

class TidalApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Tidal Downloader")
        self.geometry("1080x740")
        self.minsize(860, 600)
        self.configure(fg_color=BG)

        self.client = TidalClient()
        self._download_dir = Path.home() / "Music" / "Tidal"
        self._fmt_var      = ctk.StringVar(value="mp3")
        self._quality_var  = ctk.StringVar(value="320")

        self._queue = DownloadQueue(
            tidal_client=self.client,
            downloader_factory=self._make_downloader,
            on_update=self._on_queue_update,
        )
        self._queue_rows: dict[str, QueueRow] = {}

        self._track_rows: list[TrackRow] = []
        self._search_results: list[TrackInfo] = []
        self._csv_cards: list[tuple[CsvFileCard, list[SongEntry]]] = []

        self._build_ui()
        self._queue.start()
        self._try_auto_login()

    # ══════════════════════════════════════════════════════════════════════════
    # UI construction
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        self.sidebar = ctk.CTkFrame(self, width=230, fg_color=SURFACE, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        self._build_sidebar()

        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.pack(side="left", fill="both", expand=True)
        self._build_tabview()

    # ── Sidebar ───────────────────────────────────────────────────────────────

    def _build_sidebar(self):
        sb = self.sidebar

        logo = ctk.CTkFrame(sb, fg_color="transparent")
        logo.pack(fill="x", padx=16, pady=(22, 8))
        ctk.CTkLabel(logo, text="⬡", font=("Segoe UI", 30), text_color=ACCENT).pack(side="left")
        ctk.CTkLabel(logo, text=" TIDAL\nDL", font=("Segoe UI", 14, "bold"),
                     text_color=TEXT, justify="left").pack(side="left", padx=4)

        Divider(sb).pack(fill="x", padx=16, pady=10)

        SectionLabel(sb, "Account").pack(anchor="w", padx=16)
        self.auth_status = ctk.CTkLabel(sb, text="Not connected", font=FS, text_color=DANGER)
        self.auth_status.pack(anchor="w", padx=16, pady=2)

        self.login_btn = ctk.CTkButton(
            sb, text="Login with Tidal", height=34,
            fg_color=ACCENT, hover_color="#00A8CC",
            text_color="#000000", font=("Segoe UI", 11, "bold"),
            corner_radius=8, command=self._do_login,
        )
        self.login_btn.pack(fill="x", padx=16, pady=(6, 2))

        self.logout_btn = ctk.CTkButton(
            sb, text="Logout", height=28,
            fg_color="transparent", hover_color=CARD,
            text_color=MUTED, font=FS,
            border_width=1, border_color=BORDER,
            corner_radius=8, command=self._do_logout, state="disabled",
        )
        self.logout_btn.pack(fill="x", padx=16, pady=2)

        Divider(sb).pack(fill="x", padx=16, pady=12)

        SectionLabel(sb, "Settings").pack(anchor="w", padx=16)

        ctk.CTkLabel(sb, text="Format", font=FS, text_color=MUTED
                     ).pack(anchor="w", padx=16, pady=(6, 0))
        ctk.CTkOptionMenu(sb, values=["mp3", "m4a", "flac", "opus"],
                          variable=self._fmt_var,
                          fg_color=CARD, button_color=ACCENT,
                          button_hover_color="#00A8CC", text_color=TEXT,
                          font=FS, corner_radius=8,
                          ).pack(fill="x", padx=16, pady=(2, 8))

        ctk.CTkLabel(sb, text="Quality (kbps)", font=FS, text_color=MUTED
                     ).pack(anchor="w", padx=16)
        ctk.CTkOptionMenu(sb, values=["128", "192", "256", "320"],
                          variable=self._quality_var,
                          fg_color=CARD, button_color=ACCENT,
                          button_hover_color="#00A8CC", text_color=TEXT,
                          font=FS, corner_radius=8,
                          ).pack(fill="x", padx=16, pady=(2, 8))

        ctk.CTkLabel(sb, text="Output folder", font=FS, text_color=MUTED
                     ).pack(anchor="w", padx=16)
        self.dir_lbl = ctk.CTkLabel(sb, text=str(self._download_dir),
                                     font=FS, text_color=MUTED,
                                     wraplength=190, justify="left")
        self.dir_lbl.pack(anchor="w", padx=16, pady=(0, 4))
        ctk.CTkButton(sb, text="Browse…", height=28,
                      fg_color="transparent", hover_color=CARD,
                      text_color=ACCENT, font=FS,
                      border_width=1, border_color=BORDER,
                      corner_radius=8, command=self._choose_dir,
                      ).pack(fill="x", padx=16, pady=2)

        Divider(sb).pack(fill="x", padx=16, pady=12)

        self.queue_stat = ctk.CTkLabel(sb, text="Queue: 0 pending",
                                        font=FS, text_color=MUTED)
        self.queue_stat.pack(anchor="w", padx=16)

        ctk.CTkButton(sb, text="Clear Finished", height=28,
                      fg_color="transparent", hover_color=CARD,
                      text_color=MUTED, font=FS,
                      border_width=1, border_color=BORDER,
                      corner_radius=8, command=self._clear_finished,
                      ).pack(fill="x", padx=16, pady=(6, 2))

        Divider(sb).pack(fill="x", padx=16, pady=12)

        self._log_shown = False
        self.log_btn = ctk.CTkButton(sb, text="Show Log", height=28,
                                      fg_color="transparent", hover_color=CARD,
                                      text_color=MUTED, font=FS,
                                      border_width=1, border_color=BORDER,
                                      corner_radius=8, command=self._toggle_log)
        self.log_btn.pack(fill="x", padx=16, pady=2)

        ctk.CTkLabel(sb, text="v2.0  ·  yt-dlp + ffmpeg",
                     font=FS, text_color=MUTED).pack(side="bottom", pady=10)

    # ── Tab view ──────────────────────────────────────────────────────────────

    def _build_tabview(self):
        self.tabs = ctk.CTkTabview(
            self.content,
            fg_color=BG,
            segmented_button_fg_color=SURFACE,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color="#00A8CC",
            segmented_button_unselected_color=SURFACE,
            segmented_button_unselected_hover_color=CARD,
            text_color=TEXT,
            text_color_disabled=MUTED,
        )
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        self.tabs.add("🔍  Search")
        self.tabs.add("📂  CSV Import")
        self.tabs.add("⬇  Queue")

        self._build_search_tab(self.tabs.tab("🔍  Search"))
        self._build_csv_tab(self.tabs.tab("📂  CSV Import"))
        self._build_queue_tab(self.tabs.tab("⬇  Queue"))

        # Shared log box below tabs
        self.log_frame = ctk.CTkFrame(self.content, fg_color=SURFACE,
                                       corner_radius=10, height=130)
        self.log_text = ctk.CTkTextbox(self.log_frame, height=110, font=FM,
                                        fg_color="transparent", text_color=MUTED)
        self.log_text.pack(fill="both", padx=8, pady=4)

    # ── Search tab ────────────────────────────────────────────────────────────

    def _build_search_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        bar = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=12)
        bar.grid(row=0, column=0, sticky="ew", pady=(8, 6))
        bar.columnconfigure(0, weight=1)

        self.search_var = ctk.StringVar()
        self.search_entry = ctk.CTkEntry(
            bar, textvariable=self.search_var,
            placeholder_text="Search tracks, artists, albums…",
            height=44, font=("Segoe UI", 13),
            fg_color=CARD, border_color=BORDER,
            text_color=TEXT, placeholder_text_color=MUTED, corner_radius=10,
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(12, 6), pady=10)
        self.search_entry.bind("<Return>", lambda e: self._do_search())

        self.search_btn = ctk.CTkButton(
            bar, text="Search", width=100, height=44,
            fg_color=ACCENT, hover_color="#00A8CC",
            text_color="#000000", font=("Segoe UI", 12, "bold"),
            corner_radius=10, command=self._do_search,
        )
        self.search_btn.grid(row=0, column=1, padx=(0, 12), pady=10)

        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.grid(row=1, column=0, sticky="ew", pady=(0, 2))
        self.result_lbl = ctk.CTkLabel(hdr, text="Search results will appear here",
                                        font=FS, text_color=MUTED)
        self.result_lbl.pack(side="left")
        self.spinner_lbl = ctk.CTkLabel(hdr, text="", font=FB, text_color=ACCENT)
        self.spinner_lbl.pack(side="right", padx=4)
        self.dl_all_btn = ctk.CTkButton(
            hdr, text="⬇  Queue All", width=110, height=28,
            fg_color=ACCENT2, hover_color="#7D3C98",
            text_color=TEXT, font=FSB, corner_radius=7,
            command=self._queue_all_search, state="disabled",
        )
        self.dl_all_btn.pack(side="right", padx=4)

        self.results_scroll = ctk.CTkScrollableFrame(
            parent, fg_color=BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED,
        )
        self.results_scroll.grid(row=2, column=0, sticky="nsew", pady=(0, 4))
        self.results_scroll.columnconfigure(0, weight=1)

    # ── CSV tab ───────────────────────────────────────────────────────────────

    def _build_csv_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        top = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=12)
        top.grid(row=0, column=0, sticky="ew", pady=(8, 6))
        top.columnconfigure(0, weight=1)

        ctk.CTkLabel(top, text="Import CSV / semicolon-separated radio log files",
                     font=FB, text_color=MUTED).pack(side="left", padx=16, pady=12)

        ctk.CTkButton(top, text="Queue All Files", width=120, height=34,
                      fg_color=ACCENT2, hover_color="#7D3C98",
                      text_color=TEXT, font=FSB, corner_radius=8,
                      command=self._queue_all_csvs,
                      ).pack(side="right", padx=(0, 8), pady=10)

        ctk.CTkButton(top, text="+ Add CSV File(s)", width=140, height=34,
                      fg_color=ACCENT, hover_color="#00A8CC",
                      text_color="#000000", font=FSB, corner_radius=8,
                      command=self._import_csvs,
                      ).pack(side="right", padx=16, pady=10)

        self.csv_scroll = ctk.CTkScrollableFrame(
            parent, fg_color=BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED,
        )
        self.csv_scroll.grid(row=1, column=0, sticky="nsew", pady=(0, 4))
        self.csv_scroll.columnconfigure(0, weight=1)

        self.csv_placeholder = ctk.CTkLabel(
            self.csv_scroll,
            text="No CSV files loaded.\nClick '+ Add CSV File(s)' to import.",
            font=FB, text_color=MUTED,
        )
        self.csv_placeholder.grid(row=0, column=0, pady=60)

    # ── Queue tab ─────────────────────────────────────────────────────────────

    def _build_queue_tab(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(parent, fg_color=SURFACE, corner_radius=12)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(8, 6))

        self.queue_count_lbl = ctk.CTkLabel(toolbar, text="No jobs yet",
                                             font=FB, text_color=MUTED)
        self.queue_count_lbl.pack(side="left", padx=16, pady=10)

        ctk.CTkButton(toolbar, text="Retry Failed", width=100, height=30,
                      fg_color="transparent", hover_color=CARD,
                      text_color=DANGER, font=FSB,
                      border_width=1, border_color=DANGER,
                      corner_radius=7, command=self._retry_all_failed,
                      ).pack(side="right", padx=(4, 16), pady=8)

        ctk.CTkButton(toolbar, text="Clear Finished", width=110, height=30,
                      fg_color="transparent", hover_color=CARD,
                      text_color=MUTED, font=FSB,
                      border_width=1, border_color=BORDER,
                      corner_radius=7, command=self._clear_finished,
                      ).pack(side="right", padx=4, pady=8)

        self.queue_scroll = ctk.CTkScrollableFrame(
            parent, fg_color=BG,
            scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=MUTED,
        )
        self.queue_scroll.grid(row=1, column=0, sticky="nsew", pady=(0, 4))
        self.queue_scroll.columnconfigure(0, weight=1)

        self.queue_placeholder = ctk.CTkLabel(
            self.queue_scroll,
            text="Download queue is empty.\nSearch tracks or import a CSV to get started.",
            font=FB, text_color=MUTED,
        )
        self.queue_placeholder.grid(row=0, column=0, pady=60)

    # ══════════════════════════════════════════════════════════════════════════
    # Auth
    # ══════════════════════════════════════════════════════════════════════════

    def _try_auto_login(self):
        def task():
            ok = self.client.try_restore_session()
            self.after(0, lambda: self._on_auth_change(ok))
        threading.Thread(target=task, daemon=True).start()

    def _do_login(self):
        self.login_btn.configure(state="disabled", text="Opening browser…")

        def url_cb(url):
            self.after(0, lambda: self._on_oauth_url(url))

        def done_cb(ok):
            self.after(0, lambda: self._on_auth_change(ok))

        def task():
            try:
                self.client.login_oauth(url_cb, done_cb)
            except Exception as exc:
                self.after(0, lambda: self._log(f"Login error: {exc}"))
                self.after(0, lambda: self._on_auth_change(False))

        threading.Thread(target=task, daemon=True).start()

    def _on_oauth_url(self, url: str):
        self._log(f"Auth URL: {url}")
        try:
            webbrowser.open(url)
        except Exception:
            pass
        messagebox.showinfo("Tidal Login",
                            f"Open this URL to authorise:\n\n{url}")

    def _do_logout(self):
        self.client.logout()
        self._on_auth_change(False)

    def _on_auth_change(self, ok: bool):
        if ok:
            self.auth_status.configure(text="✓  Connected", text_color=SUCCESS)
            self.login_btn.configure(state="disabled", text="Connected")
            self.logout_btn.configure(state="normal")
            self._log("Session active.")
        else:
            self.auth_status.configure(text="Not connected", text_color=DANGER)
            self.login_btn.configure(state="normal", text="Login with Tidal")
            self.logout_btn.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    # Search
    # ══════════════════════════════════════════════════════════════════════════

    def _do_search(self):
        query = self.search_var.get().strip()
        if not query:
            return
        if not self.client.logged_in:
            messagebox.showwarning("Not logged in", "Please login to Tidal first.")
            return
        self._clear_results()
        self.search_btn.configure(state="disabled")
        self.spinner_lbl.configure(text="Searching…")
        self._log(f"Searching: {query}")

        def task():
            try:
                raw = self.client.search_tracks(query, limit=40)
                tracks = [TrackInfo(t) for t in raw]
            except Exception as exc:
                tracks = []
                self.after(0, lambda: self._log(f"Search error: {exc}"))
            self.after(0, lambda: self._on_search_done(tracks))

        threading.Thread(target=task, daemon=True).start()

    def _on_search_done(self, tracks: list[TrackInfo]):
        self.search_btn.configure(state="normal")
        self.spinner_lbl.configure(text="")
        self._search_results = tracks
        if not tracks:
            self.result_lbl.configure(text="No results found.")
            return
        self.result_lbl.configure(text=f"{len(tracks)} tracks found")
        self.dl_all_btn.configure(state="normal")
        for i, t in enumerate(tracks):
            row = TrackRow(self.results_scroll, t, on_download=self._queue_from_row)
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
            self._track_rows.append(row)

    def _clear_results(self):
        for r in self._track_rows:
            r.destroy()
        self._track_rows.clear()
        self._search_results.clear()
        self.result_lbl.configure(text="")
        self.dl_all_btn.configure(state="disabled")

    def _queue_from_row(self, row: TrackRow):
        if not self.client.logged_in:
            messagebox.showwarning("Not logged in", "Please login first.")
            return
        t = row.track_info
        self._queue.add(t.artist, t.name)
        row.set_status("queued")
        self._log(f"Queued: {t}")
        self.tabs.set("⬇  Queue")

    def _queue_all_search(self):
        if not self.client.logged_in:
            messagebox.showwarning("Not logged in", "Please login first.")
            return
        entries = [SongEntry(t.artist, t.name) for t in self._search_results]
        added = self._queue.add_many(entries)
        for row in self._track_rows:
            row.set_status("queued")
        self._log(f"Queued {len(added)} tracks from search results.")
        self.tabs.set("⬇  Queue")

    # ══════════════════════════════════════════════════════════════════════════
    # CSV import
    # ══════════════════════════════════════════════════════════════════════════

    def _import_csvs(self):
        paths = filedialog.askopenfilenames(
            title="Select CSV / semicolon-separated files",
            filetypes=[("CSV / TXT files", "*.csv *.txt *.tsv"), ("All files", "*.*")],
        )
        for p in paths:
            self._load_csv(Path(p))

    def _load_csv(self, path: Path):
        try:
            entries = parse_csv(path)
        except Exception as exc:
            messagebox.showerror("CSV Error", f"Could not parse {path.name}:\n{exc}")
            return
        if not entries:
            messagebox.showinfo("CSV Import", f"No valid tracks found in {path.name}")
            return
        self._log(f"CSV: {path.name} — {len(entries)} unique tracks")
        self.csv_placeholder.grid_remove()
        card = CsvFileCard(
            self.csv_scroll, path, entries,
            on_queue_all=self._queue_csv_entries,
            on_remove=self._remove_csv_card,
        )
        card.grid(row=len(self._csv_cards), column=0, sticky="ew", pady=4, padx=2)
        self._csv_cards.append((card, entries))

    def _queue_csv_entries(self, entries: list[SongEntry]):
        if not self.client.logged_in:
            messagebox.showwarning("Not logged in", "Please login to Tidal first.")
            return
        added = self._queue.add_many(entries)
        self._log(f"Queued {len(added)} new tracks from CSV.")
        self.tabs.set("⬇  Queue")

    def _queue_all_csvs(self):
        all_entries: list[SongEntry] = []
        for _, entries in self._csv_cards:
            all_entries.extend(entries)
        if not all_entries:
            messagebox.showinfo("CSV Import", "No CSV files loaded.")
            return
        self._queue_csv_entries(all_entries)

    def _remove_csv_card(self, card: CsvFileCard):
        self._csv_cards = [(c, e) for c, e in self._csv_cards if c is not card]
        card.destroy()
        for i, (c, _) in enumerate(self._csv_cards):
            c.grid(row=i, column=0, sticky="ew", pady=4, padx=2)
        if not self._csv_cards:
            self.csv_placeholder.grid(row=0, column=0, pady=60)

    # ══════════════════════════════════════════════════════════════════════════
    # Queue
    # ══════════════════════════════════════════════════════════════════════════

    def _make_downloader(self, progress_cb=None) -> TidalDownloader:
        return TidalDownloader(
            download_dir=self._download_dir,
            quality=self._quality_var.get(),
            fmt=self._fmt_var.get(),
            progress_cb=progress_cb,
        )

    def _on_queue_update(self, job: QueueJob):
        self.after(0, lambda: self._apply_queue_update(job))

    def _apply_queue_update(self, job: QueueJob):
        if job.job_id in self._queue_rows:
            self._queue_rows[job.job_id].update_job(job)
        else:
            self.queue_placeholder.grid_remove()
            idx = len(self._queue_rows)
            row = QueueRow(
                self.queue_scroll, job,
                on_cancel=self._cancel_job,
                on_retry=self._retry_job,
            )
            row.grid(row=idx, column=0, sticky="ew", pady=3, padx=2)
            self._queue_rows[job.job_id] = row

        # Update stats
        jobs = self._queue.jobs
        pending = sum(1 for j in jobs if j.status in (
            JobStatus.PENDING, JobStatus.SEARCHING,
            JobStatus.DOWNLOADING, JobStatus.PROCESSING))
        done    = sum(1 for j in jobs if j.status == JobStatus.DONE)
        failed  = sum(1 for j in jobs if j.status == JobStatus.FAILED)
        total   = len(jobs)

        self.queue_stat.configure(text=f"Queue: {pending} pending / {total} total")
        self.queue_count_lbl.configure(
            text=f"{total} jobs  ·  {done} done  ·  {failed} failed  ·  {pending} pending"
        )

        if job.status == JobStatus.DONE:
            self._log(f"✓ {job.label()}")
        elif job.status == JobStatus.FAILED:
            self._log(f"✗ {job.label()} — {job.error}")

    def _cancel_job(self, job_id: str):
        self._queue.cancel(job_id)

    def _retry_job(self, job_id: str):
        self._queue.retry(job_id)
        self._log(f"Retrying #{job_id}")

    def _retry_all_failed(self):
        retried = sum(
            1 for j in self._queue.jobs if j.status == JobStatus.FAILED
            and not self._queue.retry(j.job_id) is None
        )
        # retry returns None, so just iterate properly
        count = 0
        for j in self._queue.jobs:
            if j.status == JobStatus.FAILED:
                self._queue.retry(j.job_id)
                count += 1
        if count:
            self._log(f"Retrying {count} failed jobs.")

    def _clear_finished(self):
        self._queue.clear_finished()
        live_ids = {j.job_id for j in self._queue.jobs}
        dead = [jid for jid in self._queue_rows if jid not in live_ids]
        for jid in dead:
            self._queue_rows[jid].destroy()
            del self._queue_rows[jid]
        for i, row in enumerate(self._queue_rows.values()):
            row.grid(row=i, column=0, sticky="ew", pady=3, padx=2)
        if not self._queue_rows:
            self.queue_placeholder.grid(row=0, column=0, pady=60)

    # ══════════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════════

    def _choose_dir(self):
        d = filedialog.askdirectory(title="Choose download folder",
                                    initialdir=str(self._download_dir))
        if d:
            self._download_dir = Path(d)
            self.dir_lbl.configure(text=str(self._download_dir))

    def _toggle_log(self):
        if self._log_shown:
            self.log_frame.pack_forget()
            self.log_btn.configure(text="Show Log")
        else:
            self.log_frame.pack(fill="x", padx=12, pady=(0, 10))
            self.log_btn.configure(text="Hide Log")
        self._log_shown = not self._log_shown

    def _log(self, msg: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def destroy(self):
        self._queue.stop()
        super().destroy()