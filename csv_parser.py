"""
csv_parser.py — parse radio-log CSV files into unique (artist, title) pairs.

Supported column names (case-insensitive, any order):
  "Artist - Title"  →  split on first " - "
  "Artist"  +  "Title"  →  separate columns
  "artist"  +  "song" / "track"  →  alternative names

The file from the user looks like:
  Play time;Listen num;Artist - Title
  17.05 17:24 - Play Radio 91.6 FM;Eminem - Lose Yourself;
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_SPLIT_RE = re.compile(r"\s*(?:(?:-)|\u2013|\u2014)\s*")  # hyphen, en-dash, em-dash
_NORMALISE_HEADER_RE = re.compile(r"[^\w]+")  # non-alphanumeric -> separator


@dataclass(frozen=True)
class SongEntry:
    artist: str
    title: str

    def __str__(self) -> str:
        return f"{self.artist} - {self.title}"

    def search_query(self) -> str:
        return f"{self.artist} {self.title}"


# Characters / patterns to clean from raw station noise at end of title
_NOISE_RE = re.compile(
    r"\s*[\(\[]?\d{3,4}\s*kbps[\)\]]?\s*[-–]?\s*$"   # "128 kbps -"
    r"|\s*[-–]\s*$"                                      # trailing " -"
    r"|\s*❄️.*$"                                         # emoji garbage
    r"|\s*\*.*$",                                        # "* 2026 CD-single"
    re.IGNORECASE,
)


def _clean(s: str) -> str:
    s = s.strip().strip(";").strip()
    s = _NOISE_RE.sub("", s)
    return s.strip()


def _split_artist_title(val: str) -> Optional[tuple[str, str]]:
    """
    Try to split strings like:
      'Eminem - Lose Yourself'
      'Olivia Addams x @vescanofficial - Sătui de probleme'
      'Bad Bunny, Drake - MIA'
    Returns (artist, title) or None.
    """
    if not val:
        return None
    val = val.strip()
    val = val.rstrip(";,")
    parts = _SPLIT_RE.split(val, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        artist = parts[0].strip()
        title = parts[1].strip()
        return artist, title
    return None

def _normalise_header(name: str) -> str:
    s = name.strip().lower()
    s = _NORMALISE_HEADER_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def parse_csv(path: Path | str) -> list[SongEntry]:
    path = Path(path)
    raw = path.read_bytes()

    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1", errors="replace")

    sample = text[:2048]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter, skipinitialspace=True)

    if reader.fieldnames is None:
        return []

    norm_headers = { _normalise_header(h): h for h in reader.fieldnames }

    seen: set[tuple[str, str]] = set()
    entries: list[SongEntry] = []

    for row in reader:
        artist: Optional[str] = None
        title: Optional[str] = None

        for key in ("artist - title", "artist title", "artist", "artist_title", "artist-title", "artist/title", "song", "track", "title"):
            nh = key 
            col = norm_headers.get(nh)
            if col:
                val = _clean(row.get(col, ""))
                # if header is just "artist" but the value contains " - " then try split
                if nh in ("artist", "song", "track", "title") and " - " in val or "\u2013" in val or "\u2014" in val:
                    res = _split_artist_title(val)
                    if res:
                        artist, title = res
                        break
                # if header resembles combined "artist - title" try split immediately
                if nh in ("artist - title", "artist title", "artist-title", "artist_title"):
                    res = _split_artist_title(val)
                    if res:
                        artist, title = res
                        break

        # Strategy 2: separate artist + title/song columns
        if not (artist and title):
            a_col = norm_headers.get("artist")
            t_col = norm_headers.get("title") or norm_headers.get("song")
            if a_col and t_col:
                a = _clean(row.get(a_col, ""))
                t = _clean(row.get(t_col, ""))
                if a and t:
                    artist, title = a, t

        # Strategy 3: last non-empty column fallback
        if not (artist and title):
            # find last non-empty column in the row
            for col_name in reversed(reader.fieldnames):
                val = _clean(row.get(col_name, ""))
                if val:
                    res = _split_artist_title(val)
                    if res:
                        artist, title = res
                        break

        if not (artist and title):
            continue

        key_pair = (artist.lower(), title.lower())
        if key_pair not in seen:
            seen.add(key_pair)
            entries.append(SongEntry(artist=artist, title=title))

    return entries