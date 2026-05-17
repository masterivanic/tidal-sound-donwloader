"""
tidal_client.py — thin wrapper around tidalapi for auth & search
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import tidalapi

SESSION_FILE = Path.home() / ".tidal_downloader_session.json"


class TidalClient:
    def __init__(self):
        self.session = tidalapi.Session()
        self._logged_in = False

    # ── auth ──────────────────────────────────────────────────────────────────

    def login_oauth(self, url_cb, code_cb) -> bool:
        """
        Start OAuth device login.
        url_cb(url)  — called with the URL the user must visit
        code_cb()    — called when login is confirmed (or failed)
        Returns True on success.
        """
        try:
            login, future = self.session.login_oauth()
            url_cb(login.verification_uri_complete)
            future.result()
            self._logged_in = self.session.check_login()
            if self._logged_in:
                self._save_session()
            code_cb(self._logged_in)
            return self._logged_in
        except Exception as exc:
            code_cb(False)
            raise

    def try_restore_session(self) -> bool:
        """Load a previously saved OAuth session, return True if still valid."""
        if SESSION_FILE.exists():
            try:
                with open(SESSION_FILE) as f:
                    data = json.load(f)
                self.session.load_oauth_session(
                    token_type=data["token_type"],
                    access_token=data["access_token"],
                    refresh_token=data["refresh_token"],
                    expiry_time=data.get("expiry_time"),
                )
                self._logged_in = self.session.check_login()
                return self._logged_in
            except Exception:
                return False
        return False

    def _save_session(self):
        data = {
            "token_type": self.session.token_type,
            "access_token": self.session.access_token,
            "refresh_token": self.session.refresh_token,
            "expiry_time": str(self.session.expiry_time) if self.session.expiry_time else None,
        }
        with open(SESSION_FILE, "w") as f:
            json.dump(data, f)

    def logout(self):
        self._logged_in = False
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()

    @property
    def logged_in(self) -> bool:
        return self._logged_in

    # ── search ────────────────────────────────────────────────────────────────

    def search_tracks(self, query: str, limit: int = 30) -> list:
        """Return a list of tidalapi.Track objects."""
        if not self._logged_in:
            return []
        results = self.session.search(query, models=[tidalapi.Track], limit=limit)
        return results.get("tracks", [])

    def search_albums(self, query: str, limit: int = 10) -> list:
        if not self._logged_in:
            return []
        results = self.session.search(query, models=[tidalapi.Album], limit=limit)
        return results.get("albums", [])

    def get_album_tracks(self, album_id: int) -> list:
        if not self._logged_in:
            return []
        album = self.session.album(album_id)
        return list(album.tracks())
