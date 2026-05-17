"""
downloader.py — Tidal track downloader using yt-dlp + ffmpeg
Adapted & extended from the original Spotify-based downloader.
"""
from __future__ import annotations

import time
from multiprocessing import cpu_count
from multiprocessing.pool import ThreadPool
from os import remove
from pathlib import Path
from shutil import Error as ShutilError, move
from typing import Any, Callable, Optional

from ffmpy import FFmpeg, FFRuntimeError
from yt_dlp import YoutubeDL

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def safe_path_string(s: str) -> str:
    """Remove / replace characters that are illegal in file-system paths."""
    for ch in r'\/:*?"<>|':
        s = s.replace(ch, "_")
    return s.strip()


def check_file(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def create_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def clean(directory: Path) -> None:
    if directory.exists():
        for item in directory.iterdir():
            if item.is_file():
                try:
                    item.unlink()
                except OSError:
                    pass


# ──────────────────────────────────────────────────────────────────────────────
# Data-classes
# ──────────────────────────────────────────────────────────────────────────────

class TrackInfo:
    """Lightweight container for Tidal track metadata."""

    def __init__(self, tidal_track):
        self.id: str = str(tidal_track.id)
        self.name: str = tidal_track.name
        self.artist: str = (
            tidal_track.artist.name if tidal_track.artist else "Unknown Artist"
        )
        self.album: str = (
            tidal_track.album.name if tidal_track.album else "Unknown Album"
        )
        self.duration: int = getattr(tidal_track, "duration", 0)
        self.track_number: int = getattr(tidal_track, "track_num", 1)
        self.isrc: str = getattr(tidal_track, "isrc", "") or ""
        self.cover_url: str = self._cover_url(tidal_track)

    @staticmethod
    def _cover_url(track) -> str:
        try:
            return track.album.image(640)
        except Exception:
            return ""

    def __str__(self) -> str:
        return f"{self.artist} - {self.name}"

    def search_query(self) -> str:
        return f"ytsearch:{self.artist} {self.name} audio"


# ──────────────────────────────────────────────────────────────────────────────
# Downloader
# ──────────────────────────────────────────────────────────────────────────────

class TidalDownloader:
    """
    Download Tidal tracks via yt-dlp / ffmpeg.

    Parameters
    ----------
    download_dir : Path
        Where finished files land.
    quality : str
        ffmpeg preferred quality (0–9 for VBR, or bitrate like '320').
    fmt : str
        Output container / codec: 'mp3', 'flac', 'm4a', 'opus', …
    ffmpeg_location : str
        Path to ffmpeg binary, or 'ffmpeg' if it is on $PATH.
    retry : int
        How many times to retry a failed download.
    progress_cb : Callable[[str, str, float], None] | None
        Called with (track_str, status, 0–1 progress).
    logger : Any
        Object with .info() / .error() methods (or None).
    """

    def __init__(
        self,
        download_dir: Path,
        quality: str = "320",
        fmt: str = "mp3",
        ffmpeg_location: str = "ffmpeg",
        retry: int = 3,
        progress_cb: Optional[Callable] = None,
        logger: Any = None,
        skip_cover_art: bool = False,
    ):
        self.download_dir = Path(download_dir)
        self.quality = quality
        self.fmt = fmt
        self.ffmpeg_location = ffmpeg_location
        self.retry = retry
        self.progress_cb = progress_cb
        self.logger = logger
        self.skip_cover_art = skip_cover_art

        self._temp_dir = self.download_dir / ".tmp"
        create_dir(self._temp_dir)
        create_dir(self.download_dir)

        self._cover_cache: dict[str, Path] = {}

    # ── public ────────────────────────────────────────────────────────────────

    def download_tracks(self, tracks: list[TrackInfo]) -> dict:
        """
        Download a list of TrackInfo objects concurrently.
        Returns a summary dict: {completed, failed, total, elapsed}.
        """
        clean(self._temp_dir)
        start = time.time()

        workers = min(cpu_count(), len(tracks), 4)  # cap at 4 to be polite
        with ThreadPool(workers) as pool:
            results = pool.map(self._download_one, tracks)

        failed = [r for r in results if r["returncode"] != 0]
        clean(self._temp_dir)

        return {
            "total": len(tracks),
            "completed": len(tracks) - len(failed),
            "failed": failed,
            "elapsed": time.time() - start,
        }

    def download_single(self, track: TrackInfo) -> dict:
        """Download a single track synchronously. Returns status dict."""
        return self._download_one(track)

    # ── private ───────────────────────────────────────────────────────────────

    def _notify(self, track: TrackInfo, status: str, progress: float = 0.0):
        if self.progress_cb:
            self.progress_cb(str(track), status, progress)

    def _ydl_progress_hook(self, track: TrackInfo):
        def hook(data):
            if data["status"] == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate", 1)
                done = data.get("downloaded_bytes", 0)
                self._notify(track, "downloading", done / max(total, 1))
            elif data["status"] == "finished":
                self._notify(track, "processing", 0.9)
        return hook

    def _build_ydl_options(self, track: TrackInfo, output_temp: str) -> dict:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": output_temp,
            "restrictfilenames": True,
            "ignoreerrors": True,
            "nooverwrites": True,
            "noplaylist": True,
            "prefer_ffmpeg": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._ydl_progress_hook(track)],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.fmt,
                    "preferredquality": self.quality,
                }
            ],
            "postprocessor_args": [
                "-write_id3v1", "1",
                "-id3v2_version", "3",
                "-metadata", f"title={track.name}",
                "-metadata", f"album={track.album}",
                "-metadata", f"artist={track.artist}",
                "-metadata", f"track={track.track_number}",
                "-metadata", f"isrc={track.isrc}",
            ],
        }
        if self.fmt == "mp3":
            opts["postprocessor_args"] += ["-codec:a", "libmp3lame"]
        if self.ffmpeg_location != "ffmpeg":
            opts["ffmpeg_location"] = self.ffmpeg_location
        return opts

    def _download_one(self, track: TrackInfo) -> dict:
        status: dict = {"track": track, "returncode": -1}

        output = self.download_dir / safe_path_string(f"{track}.{self.fmt}")
        output_temp_pattern = str(self._temp_dir / f"{track.id}.%(ext)s")
        output_temp = str(self._temp_dir / f"{track.id}.{self.fmt}")

        if check_file(output):
            self._notify(track, "skipped", 1.0)
            status["returncode"] = 0
            return status

        self._notify(track, "queued", 0.0)

        options = self._build_ydl_options(track, output_temp_pattern)
        query = track.search_query()

        attempt = 0
        downloaded = False

        while not downloaded:
            attempt += 1
            try:
                with YoutubeDL(options) as ydl:
                    ydl.download([query])
                if check_file(Path(output_temp)):
                    downloaded = True
                else:
                    if attempt > self.retry:
                        status["returncode"] = 1
                        status["error"] = "yt-dlp could not find audio."
                        self._notify(track, "failed", 0.0)
                        return status
            except Exception as exc:
                if attempt > self.retry:
                    status["returncode"] = 1
                    status["error"] = str(exc)
                    self._notify(track, "failed", 0.0)
                    return status

        # Embed cover art (MP3 only, unless skipped)
        if self.fmt == "mp3" and not self.skip_cover_art and track.cover_url:
            self._embed_cover(track, output_temp, output)
        else:
            try:
                move(output_temp, output)
            except ShutilError as exc:
                status["returncode"] = 1
                status["error"] = f"Filesystem error: {exc}"
                self._notify(track, "failed", 0.0)
                return status

        status["returncode"] = 0
        self._notify(track, "done", 1.0)
        return status

    def _embed_cover(self, track: TrackInfo, src: str, dest: Path) -> None:
        """Download cover art and mux it into the MP3 file via ffmpeg."""
        import urllib.request, tempfile

        cover_key = track.cover_url
        if cover_key not in self._cover_cache:
            try:
                tmp = tempfile.NamedTemporaryFile(
                    suffix=".jpg", delete=False, dir=self._temp_dir
                )
                urllib.request.urlretrieve(track.cover_url, tmp.name)
                self._cover_cache[cover_key] = Path(tmp.name)
            except Exception:
                # No cover — just move the file as-is
                try:
                    move(src, dest)
                except ShutilError:
                    pass
                return

        cover = self._cover_cache[cover_key]

        attempt = 0
        done = False
        while not done:
            attempt += 1
            ffmpeg = FFmpeg(
                executable=self.ffmpeg_location,
                inputs={src: None, str(cover): None},
                outputs={
                    str(dest): (
                        "-loglevel quiet -hide_banner -y "
                        "-map 0:0 -map 1:0 -c copy -id3v2_version 3 "
                        '-metadata:s:v title="Album cover" '
                        '-metadata:s:v comment="Cover (front)"'
                    )
                },
            )
            try:
                ffmpeg.run()
                done = True
            except FFRuntimeError:
                if attempt > self.retry:
                    try:
                        move(src, dest)
                    except ShutilError:
                        pass
                    done = True

        try:
            remove(src)
        except OSError:
            pass
