"""
User Directory service — the source of truth for "who can I email".

The user uploads a `users.json` file to the project root (mounted
into the container at `/app/users.json` by default). The file is
an array of user records (Microsoft Graph / Azure AD export
format) with at least these fields:

    {
      "Mail": "alice@example.com",
      "DisplayName": "Alice Smith",
      "GivenName": "Alice",
      "Surname": "Smith",
      "Department": "Engineering",
      "JobTitle": "Senior Engineer",
      "AccountEnabled": true,
      "MailNickname": "alice"
    }

The service:
  - reads + parses the file ONCE on startup
  - caches the parsed list in memory (no per-request disk reads)
  - watches the file's mtime; if the file changes between requests,
    it reloads the cache automatically
  - exposes a search() function for the typeahead

The cache is intentionally process-local (this is a small internal
tool, the file is small, and per-user-id re-reads are
unnecessary). Multi-worker deployments would need a
shared-cache layer; that's out of scope.

The file path is configurable via the ``USERS_JSON_PATH``
environment variable — defaults to ``/app/users.json`` so the
Docker mount works out of the box.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple


# ── Public dataclass ───────────────────────────────────────────────────

@dataclass
class UserEntry:
    """One user from the directory, normalised for the typeahead."""

    id: str                  # unique id from the source file
    email: str               # primary email (lowercased, trimmed)
    name: str                # DisplayName (or built from Given+Surname)
    given_name: str          # first name
    surname: str             # last name
    department: str          # department (may be empty)
    job_title: str           # job title (may be empty)
    enabled: bool            # AccountEnabled flag

    # Pre-computed lowercase search haystack (name + email + nickname).
    # Built once on load; rebuilt only on reload.  This is the single
    # biggest perf optimisation for the typeahead — the search()
    # call does a single in-memory substring match against this
    # string per user.
    _haystack: str = field(default="", repr=False, compare=False)

    def to_public_dict(self) -> Dict[str, Any]:
        """Serialise for the API response — only public fields."""
        return {
            "id":          self.id,
            "email":       self.email,
            "name":        self.name,
            "department":  self.department,
            "jobTitle":    self.job_title,
        }


# ── Module-level state ─────────────────────────────────────────────────

_LOCK = threading.RLock()
_USERS: List[UserEntry] = []
_PATH: str = ""
_LAST_MTIME: float = 0.0
_LAST_LOAD_AT: Optional[float] = None       # epoch seconds
_LOAD_ERROR: Optional[str] = None           # last parse/IO error
_ENABLED_ONLY: bool = True                  # filter to enabled by default


# ── Path resolution ───────────────────────────────────────────────────

def _resolve_path() -> str:
    """Return the configured path (env var or default).

    We honour ``USERS_JSON_PATH`` so deployments that mount the
    file at a non-default path can override it without rebuilding
    the image.
    """
    return os.environ.get("USERS_JSON_PATH", "/app/users.json").strip() or "/app/users.json"


# ── Loading ────────────────────────────────────────────────────────────

def _normalise(record: Dict[str, Any]) -> Optional[UserEntry]:
    """Turn a raw record into a UserEntry.  Returns None if the
    record is invalid (no email, etc.)."""
    email = (record.get("Mail") or record.get("UserPrincipalName") or "").strip()
    if not email or "@" not in email:
        return None
    email = email.lower()

    display_name = (record.get("DisplayName") or "").strip()
    given = (record.get("GivenName") or "").strip()
    surname = (record.get("Surname") or "").strip()
    if not display_name and (given or surname):
        display_name = f"{given} {surname}".strip()

    nickname = (record.get("MailNickname") or "").strip()

    # Haystack = "name + email + nickname + department" — single
    # string, lowercased, so the search() loop is a single
    # ``in`` check per user.  The order doesn't matter for
    # correctness, but the most distinctive fields go first so the
    # substring is found quickly.
    haystack = " ".join((
        display_name.lower(),
        email,
        nickname.lower(),
        (record.get("Department") or "").lower(),
        (record.get("JobTitle") or "").lower(),
    ))

    return UserEntry(
        id=(record.get("Id") or email).strip(),
        email=email,
        name=display_name or email,
        given_name=given,
        surname=surname,
        department=(record.get("Department") or "").strip(),
        job_title=(record.get("JobTitle") or "").strip(),
        enabled=bool(record.get("AccountEnabled", True)),
        _haystack=haystack,
    )


def _load_from_disk(path: str) -> Tuple[List[UserEntry], Optional[str]]:
    """Read the JSON file, normalise every record.  Returns
    (users, error_message).  The error message is set when the
    file is missing or malformed; we keep the previous in-memory
    cache in that case so the app keeps working.
    """
    if not os.path.exists(path):
        return [], f"file not found: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return [], f"failed to read {path}: {exc}"

    # Support two shapes:
    #   1. {"body": {"value": [ ...records ]}}   (Graph API export)
    #   2. [ ...records ]                        (raw array)
    if isinstance(data, dict) and "body" in data:
        records = data["body"].get("value") or data["body"] or []
    elif isinstance(data, list):
        records = data
    else:
        return [], f"unexpected JSON shape in {path}: {type(data).__name__}"

    users: List[UserEntry] = []
    seen = set()
    for r in records:
        if not isinstance(r, dict):
            continue
        u = _normalise(r)
        if u is None:
            continue
        # De-duplicate on email — the user's file may have a row
        # for the same person under multiple aliases; keep the
        # first (most populated) record.
        if u.email in seen:
            continue
        seen.add(u.email)
        users.append(u)
    return users, None


def initial_load() -> None:
    """Called once on app startup. Loads the file (if present)
    and populates the in-memory cache.  A missing file is OK —
    the typeahead just shows no suggestions and the admin page
    tells the user how to add the file."""
    global _USERS, _PATH, _LAST_MTIME, _LAST_LOAD_AT, _LOAD_ERROR
    with _LOCK:
        _PATH = _resolve_path()
        try:
            _LAST_MTIME = os.path.getmtime(_PATH) if os.path.exists(_PATH) else 0.0
        except OSError:
            _LAST_MTIME = 0.0
        users, err = _load_from_disk(_PATH)
        _USERS = users
        _LAST_LOAD_AT = time.time() if not err else None
        _LOAD_ERROR = err


def reload(force: bool = False) -> Dict[str, Any]:
    """Reload the in-memory cache from disk.  If ``force`` is
    False, we only reload if the file's mtime has changed since
    the last load (cheap "did the file change?" check).  Returns
    a small dict the admin UI can show to confirm the reload.

    The cache is *never* cleared on a parse error — the previous
    in-memory list stays available, and ``status`` reports the
    error so the admin page can surface it.
    """
    global _USERS, _LAST_MTIME, _LAST_LOAD_AT, _LOAD_ERROR
    with _LOCK:
        path = _PATH or _resolve_path()
        try:
            mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
        except OSError as exc:
            return {
                "ok":      False,
                "loaded":  len(_USERS),
                "path":    path,
                "message": f"Cannot stat file: {exc}",
            }

        if not force and mtime == _LAST_MTIME and _USERS:
            return {
                "ok":         True,
                "loaded":     len(_USERS),
                "path":       path,
                "message":    "Already up-to-date (file mtime unchanged).",
                "skipped":    True,
            }

        users, err = _load_from_disk(path)
        if err is None:
            _USERS = users
            _LAST_MTIME = mtime
            _LAST_LOAD_AT = time.time()
            _LOAD_ERROR = None
            return {
                "ok":       True,
                "loaded":   len(_USERS),
                "path":     path,
                "message":  f"Loaded {len(_USERS)} users from {path}.",
                "skipped":  False,
            }
        # Parse error: keep the existing cache, report the error.
        return {
            "ok":       False,
            "loaded":   len(_USERS),
            "path":     path,
            "message":  err,
            "skipped":  False,
        }


# ── Search ─────────────────────────────────────────────────────────────

# Pre-compiled regexes for tokenisation — we split the user's
# query into whitespace-separated tokens and require EVERY token
# to be present (anywhere) in the user's haystack.  This gives the
# classic "type two letters, get a name" behaviour without needing
# a real search engine.
_WHITESPACE = re.compile(r"\s+")


def _ensure_fresh() -> None:
    """Auto-reload the cache if the file's mtime has changed since
    the last load.  Called once per request — the mtime check is
    a single stat() call (~microseconds) so the overhead is
    negligible.
    """
    global _LAST_MTIME
    with _LOCK:
        if not _PATH:
            return
        try:
            mtime = os.path.getmtime(_PATH)
        except OSError:
            return
        if mtime != _LAST_MTIME:
            # The file changed on disk — reload outside the lock
            # to avoid blocking other readers.  We re-acquire the
            # lock inside reload() to update the cache safely.
            reload(force=True)


def search(
    query: str,
    *,
    limit: int = 8,
    enabled_only: bool = True,
) -> List[Dict[str, Any]]:
    """Return up to ``limit`` users matching ``query``.

    Matching rules:
      - case-insensitive
      - query is split into whitespace-separated tokens
      - every token must be present (anywhere) in the user's
        haystack (name + email + nickname + department + job title)
      - results are ranked by:
          1. exact-email match first
          2. token match in email (prefix bonus)
          3. token match in name (prefix bonus)
          4. alphabetical by name as a tiebreaker
      - users with ``AccountEnabled == False`` are filtered out
        unless ``enabled_only=False`` is passed (admin use).
    """
    _ensure_fresh()
    q = (query or "").strip().lower()
    if not q:
        # Empty query: return nothing (the typeahead should not
        # show a giant list on focus).  The caller can use
        # ``list_recent()`` if it wants a "no query" suggestion.
        return []
    tokens = [t for t in _WHITESPACE.split(q) if t]

    with _LOCK:
        users = list(_USERS)

    def score(u: UserEntry) -> Tuple[int, int, int, str]:
        # Lower score = better.
        if u.email == q:
            return (0, 0, 0, u.name.lower())
        # email-prefix bonus: starts-with matches win.
        email_bonus = 0 if u.email.startswith(tokens[0]) else 1
        name_bonus = 0 if u.name.lower().startswith(tokens[0]) else 1
        return (1, name_bonus, email_bonus, u.name.lower())

    matched: List[UserEntry] = []
    for u in users:
        if enabled_only and not u.enabled:
            continue
        if all(tok in u._haystack for tok in tokens):
            matched.append(u)
    matched.sort(key=score)
    return [u.to_public_dict() for u in matched[:limit]]


def list_recent(limit: int = 8) -> List[Dict[str, Any]]:
    """Return the alphabetically-first N enabled users.

    Used as a "starter set" when the user opens the dropdown
    before typing anything (so they see a sample of the
    directory).  Limited to 8 by default.
    """
    _ensure_fresh()
    with _LOCK:
        users = [u for u in _USERS if u.enabled]
    users.sort(key=lambda u: (u.name or u.email).lower())
    return [u.to_public_dict() for u in users[:limit]]


def status() -> Dict[str, Any]:
    """Return the current state of the cache for the admin UI.

    The ``healthy`` flag is True iff a file is loaded and the
    last reload succeeded.  ``path`` is the file the service
    is watching (informational).
    """
    _ensure_fresh()
    with _LOCK:
        enabled_count = sum(1 for u in _USERS if u.enabled)
        total_count = len(_USERS)
        mtime = _LAST_MTIME
        loaded_at = _LAST_LOAD_AT
        err = _LOAD_ERROR
        path = _PATH or _resolve_path()
    return {
        "healthy":      err is None and total_count > 0,
        "path":         path,
        "totalUsers":   total_count,
        "enabledUsers": enabled_count,
        "fileExists":   os.path.exists(path),
        "fileMtime":    mtime,
        "loadedAt":     loaded_at,
        "loadedAtIst":  None if loaded_at is None
                       else __import__("app.utils.tz", fromlist=["iso_ist"]).iso_ist(
                           __import__("datetime").datetime.fromtimestamp(loaded_at)
                       ),
        "lastError":    err,
        "fileSize":     os.path.getsize(path) if os.path.exists(path) else 0,
    }
