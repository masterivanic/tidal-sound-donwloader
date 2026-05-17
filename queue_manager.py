"""
queue_manager.py — persistent background download queue.

A single worker thread pulls jobs one at a time so downloads
continue regardless of what the user does in the UI.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional
from uuid import uuid4


class JobStatus(Enum):
    PENDING    = auto()
    SEARCHING  = auto()
    DOWNLOADING= auto()
    PROCESSING = auto()
    DONE       = auto()
    FAILED     = auto()
    SKIPPED    = auto()
    CANCELLED  = auto()


@dataclass
class QueueJob:
    job_id:   str
    query:    str           # "Artist - Title" search string
    artist:   str
    title:    str
    status:   JobStatus      = field(default=JobStatus.PENDING)
    error:    str            = ""
    progress: float          = 0.0
    track_info: object       = None   # set after Tidal search

    def label(self) -> str:
        return f"{self.artist} - {self.title}"


class DownloadQueue:
    """
    Thread-safe queue + worker.

    Usage:
        dq = DownloadQueue(tidal_client, downloader_factory, on_update_cb)
        dq.start()
        dq.add("Eminem", "Lose Yourself")
        ...
        dq.stop()

    Callbacks:
        on_update(job: QueueJob)  — called from the worker thread whenever
                                    a job changes state. The UI should
                                    schedule via .after(0, ...).
    """

    def __init__(
        self,
        tidal_client,
        downloader_factory: Callable,     # () -> TidalDownloader
        on_update: Callable[[QueueJob], None],
    ):
        self._client    = tidal_client
        self._dl_factory = downloader_factory
        self._on_update  = on_update

        self._pending: queue.Queue[QueueJob] = queue.Queue()
        self._all_jobs: dict[str, QueueJob]  = {}   # job_id → job
        self._lock = threading.Lock()

        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._active_job: Optional[QueueJob] = None

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        """Start the background worker thread."""
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker, daemon=True, name="dl-queue-worker"
        )
        self._worker_thread.start()

    def stop(self):
        """Signal the worker to stop after current job."""
        self._stop_event.set()

    def add(self, artist: str, title: str) -> QueueJob:
        """Add a song to the queue. Returns the QueueJob."""
        job = QueueJob(
            job_id=str(uuid4())[:8],
            query=f"{artist} {title}",
            artist=artist,
            title=title,
        )
        with self._lock:
            self._all_jobs[job.job_id] = job
        self._pending.put(job)
        self._notify(job)
        return job

    def add_many(self, entries: list) -> list[QueueJob]:
        """Add multiple SongEntry objects, skip exact duplicates already queued."""
        added = []
        with self._lock:
            existing = {
                (j.artist.lower(), j.title.lower())
                for j in self._all_jobs.values()
                if j.status not in (JobStatus.FAILED, JobStatus.CANCELLED)
            }
        for entry in entries:
            key = (entry.artist.lower(), entry.title.lower())
            if key not in existing:
                existing.add(key)
                job = self.add(entry.artist, entry.title)
                added.append(job)
        return added

    def cancel(self, job_id: str):
        """Mark a pending job as cancelled (won't start it)."""
        with self._lock:
            job = self._all_jobs.get(job_id)
            if job and job.status == JobStatus.PENDING:
                job.status = JobStatus.CANCELLED
                self._notify(job)

    def retry(self, job_id: str):
        """Re-queue a failed / cancelled job."""
        with self._lock:
            job = self._all_jobs.get(job_id)
            if job and job.status in (JobStatus.FAILED, JobStatus.CANCELLED):
                job.status = JobStatus.PENDING
                job.error  = ""
                job.progress = 0.0
        if job:
            self._pending.put(job)
            self._notify(job)

    def clear_finished(self):
        """Remove DONE / SKIPPED / CANCELLED entries from tracking."""
        with self._lock:
            remove = [
                jid for jid, j in self._all_jobs.items()
                if j.status in (JobStatus.DONE, JobStatus.SKIPPED, JobStatus.CANCELLED)
            ]
            for jid in remove:
                del self._all_jobs[jid]

    @property
    def jobs(self) -> list[QueueJob]:
        with self._lock:
            return list(self._all_jobs.values())

    @property
    def pending_count(self) -> int:
        return sum(
            1 for j in self._all_jobs.values()
            if j.status == JobStatus.PENDING
        )

    @property
    def active_job(self) -> Optional[QueueJob]:
        return self._active_job

    # ── Worker ─────────────────────────────────────────────────────────────────

    def _worker(self):
        while not self._stop_event.is_set():
            try:
                job = self._pending.get(timeout=0.5)
            except queue.Empty:
                continue

            # Skip cancelled jobs silently
            if job.status == JobStatus.CANCELLED:
                self._pending.task_done()
                continue

            self._active_job = job
            self._run_job(job)
            self._active_job = None
            self._pending.task_done()

    def _run_job(self, job: QueueJob):
        # 1. Search Tidal for the track
        self._set_status(job, JobStatus.SEARCHING)
        try:
            results = self._client.search_tracks(job.query, limit=5)
            if not results:
                raise ValueError("No results found on Tidal.")
            track_info_raw = results[0]
        except Exception as exc:
            self._set_status(job, JobStatus.FAILED, error=str(exc))
            return

        # Build TrackInfo
        from downloader import TrackInfo
        try:
            job.track_info = TrackInfo(track_info_raw)
        except Exception as exc:
            self._set_status(job, JobStatus.FAILED, error=str(exc))
            return

        # 2. Download via yt-dlp + ffmpeg
        self._set_status(job, JobStatus.DOWNLOADING)

        def progress_cb(track_str, status, progress):
            job.progress = progress
            if status == "processing":
                self._set_status(job, JobStatus.PROCESSING, progress=progress)
            elif status in ("downloading",):
                self._set_status(job, JobStatus.DOWNLOADING, progress=progress)

        dl = self._dl_factory(progress_cb=progress_cb)
        result = dl.download_single(job.track_info)

        if result["returncode"] == 0:
            self._set_status(job, JobStatus.DONE, progress=1.0)
        else:
            err = result.get("error", "Unknown error")
            self._set_status(job, JobStatus.FAILED, error=err)

    def _set_status(
        self,
        job: QueueJob,
        status: JobStatus,
        error: str = "",
        progress: float = None,
    ):
        job.status = status
        if error:
            job.error = error
        if progress is not None:
            job.progress = progress
        self._notify(job)

    def _notify(self, job: QueueJob):
        try:
            self._on_update(job)
        except Exception:
            pass