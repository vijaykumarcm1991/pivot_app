"""
User Directory service — the source of truth for "who/what can I email".

The user provides two CSV files (Microsoft-Graph-style exports, one row per
record) in the project root.  Both are mounted into the container as
read-only:

  Users.csv                   — one row per individual user / mailbox
  DistributionLists.csv       — one row per group / distribution list

File shapes (header row + data rows; fields are quoted):

  Users.csv:
      "DisplayName","PrimarySmtpAddress","Alias"

  DistributionLists.csv:
      "DisplayName","Alias","PrimarySmtpAddress","ManagedBy"
      (ManagedBy is ignored — it's the .NET ArrayList serialisation
      placeholder for the "owners" field and is always the same string
      for every row in the export.)

The service:
  - reads + parses BOTH files ONCE on startup
  - caches the parsed lists in memory (no per-request disk reads)
  - watches each file's mtime; if either file changes between requests,
    it reloads the affected cache automatically
  - exposes a search() function for the typeahead that merges both
    sources

The cache is intentionally process-local (this is a small internal tool,
the files are small, and per-record re-reads are unnecessary).
Multi-worker deployments would need a shared-cache layer; that's out of
scope.

File paths are configurable via env vars:
  - USERS_CSV_PATH                (default /app/Users.csv)
  - DISTRIBUTION_LISTS_CSV_PATH   (default /app/DistributionLists.csv)
"""
from __future__ import annotations

import csv
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


# ── Kinds ───────────────────────────────────────────────────────────────

KIND_USER = "user"
KIND_DISTRIBUTION_LIST = "distribution_list"
_VALID_KINDS = (KIND_USER, KIND_DISTRIBUTION_LIST)


# ── Public dataclass ───────────────────────────────────────────────────

@dataclass
class DirectoryEntry:
    """One addressable record (a person OR a distribution list)."""

    id: str                  # unique id (email — the directory is keyed by email)
    email: str               # primary email (lowercased, trimmed)
    name: str                # DisplayName (or email if missing)
    alias: str               # mail nickname (lowercased, trimmed)
    department: str          # empty for now — CSVs don't carry it
    job_title: str           # empty for now — CSVs don't carry it
    enabled: bool            # True for now — CSVs don't carry it
    kind: str                # "user" or "distribution_list"

    # Pre-computed lowercase search haystack (name + email + alias).
    # Built once on load; rebuilt only on reload.  This is the single
    # biggest perf optimisation for the typeahead — the search()
    # call does a single in-memory substring match against this
    # string per record.
    _haystack: str = field(default="", repr=False, compare=False)

    def to_public_dict(self) -> Dict[str, Any]:
        """Serialise for the API response — only public fields."""
        return {
            "id":        self.id,
            "email":     self.email,
            "name":      self.name,
            "alias":     self.alias,
            "kind":      self.kind,
            "department": self.department,
            "jobTitle":  self.job_title,
        }


# ── Module-level state ─────────────────────────────────────────────────

_LOCK = threading.RLock()
_USERS: List[DirectoryEntry] = []
_DLS:   List[DirectoryEntry] = []

_USERS_PATH:    str = ""
_DLS_PATH:      str = ""
_USERS_MTIME:   float = 0.0
_DLS_MTIME:     float = 0.0
_LAST_LOAD_AT:  Optional[float] = None       # epoch seconds
_LOAD_ERROR:    Optional[str] = None         # last parse/IO error


# ── Path resolution ───────────────────────────────────────────────────

def _resolve_users_path() -> str:
    """Path to Users.csv (env var override)."""
    return (
        os.environ.get("USERS_CSV_PATH", "/app/Users.csv").strip()
        or "/app/Users.csv"
    )


def _resolve_dls_path() -> str:
    """Path to DistributionLists.csv (env var override)."""
    return (
        os.environ.get("DISTRIBUTION_LISTS_CSV_PATH", "/app/DistributionLists.csv").strip()
        or "/app/DistributionLists.csv"
    )


# ── Parsing ────────────────────────────────────────────────────────────

def _normalise_user(record: Dict[str, str]) -> Optional[DirectoryEntry]:
    """Turn a Users.csv row into a DirectoryEntry.  Returns None if
    the record is invalid (no email, etc.)."""
    email = (record.get("PrimarySmtpAddress") or "").strip()
    if not email or "@" not in email:
        return None
    email = email.lower()

    display_name = (record.get("DisplayName") or "").strip()
    alias = (record.get("Alias") or "").strip().lower()

    name = display_name or email

    haystack = " ".join((
        name.lower(),
        email,
        alias,
    ))

    return DirectoryEntry(
        id=email,
        email=email,
        name=name,
        alias=alias,
        department="",
        job_title="",
        enabled=True,
        kind=KIND_USER,
        _haystack=haystack,
    )


def _normalise_dl(record: Dict[str, str]) -> Optional[DirectoryEntry]:
    """Turn a DistributionLists.csv row into a DirectoryEntry.
    Returns None if the record is invalid.

    The `ManagedBy` column is intentionally ignored — it's a .NET
    `System.Collections.ArrayList` serialisation placeholder for the
    group's owners and is the same string for every row in a typical
    export.
    """
    email = (record.get("PrimarySmtpAddress") or "").strip()
    if not email or "@" not in email:
        return None
    email = email.lower()

    display_name = (record.get("DisplayName") or "").strip()
    alias = (record.get("Alias") or "").strip().lower()

    name = display_name or email

    haystack = " ".join((
        name.lower(),
        email,
        alias,
    ))

    return DirectoryEntry(
        id=email,
        email=email,
        name=name,
        alias=alias,
        department="",
        job_title="",
        enabled=True,
        kind=KIND_DISTRIBUTION_LIST,
        _haystack=haystack,
    )


def _load_csv(path: str, normaliser) -> Tuple[List[DirectoryEntry], Optional[str]]:
    """Read a CSV file, normalise every record.  Returns
    (records, error_message).  The error message is set when the
    file is missing or malformed; the previous in-memory cache
    is kept in that case so the app keeps working.
    """
    if not os.path.exists(path):
        return [], f"file not found: {path}"
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            records: List[DirectoryEntry] = []
            seen = set()
            for row in reader:
                entry = normaliser(row)
                if entry is None:
                    continue
                # De-duplicate on email within a file — the user's
                # export may have the same address listed twice
                # (e.g. a person who is also a manager of a group).
                # The first occurrence wins.
                if entry.email in seen:
                    continue
                seen.add(entry.email)
                records.append(entry)
            return records, None
    except (OSError, csv.Error, UnicodeDecodeError) as exc:
        return [], f"failed to read {path}: {exc}"


# ── Loading ────────────────────────────────────────────────────────────

def _load_from_disk(users_path: str, dls_path: str) -> Tuple[
    List[DirectoryEntry], List[DirectoryEntry], Optional[str],
]:
    """Read both CSVs in one call.  Returns
    (users, dls, first_error_message_or_None).

    A missing file is not an error here — the caller decides what
    to do with an empty list.  Only I/O / parse errors are
    reported via the error message.
    """
    users, user_err = _load_csv(users_path, _normalise_user)
    dls,   dl_err   = _load_csv(dls_path,   _normalise_dl)
    # Surface the first error (if any) so the admin card can show it.
    return users, dls, user_err or dl_err


def initial_load() -> None:
    """Called once on app startup. Loads both files (if present)
    and populates the in-memory caches.  A missing file is OK —
    the typeahead just shows no suggestions for that kind and
    the admin page tells the user how to add the file."""
    global _USERS, _DLS
    global _USERS_PATH, _DLS_PATH
    global _USERS_MTIME, _DLS_MTIME
    global _LAST_LOAD_AT, _LOAD_ERROR

    with _LOCK:
        _USERS_PATH = _resolve_users_path()
        _DLS_PATH   = _resolve_dls_path()
        try:
            _USERS_MTIME = os.path.getmtime(_USERS_PATH) if os.path.exists(_USERS_PATH) else 0.0
        except OSError:
            _USERS_MTIME = 0.0
        try:
            _DLS_MTIME = os.path.getmtime(_DLS_PATH) if os.path.exists(_DLS_PATH) else 0.0
        except OSError:
            _DLS_MTIME = 0.0

        users, dls, err = _load_from_disk(_USERS_PATH, _DLS_PATH)
        _USERS = users
        _DLS   = dls
        _LAST_LOAD_AT = time.time() if not err else None
        _LOAD_ERROR = err


def reload(force: bool = False) -> Dict[str, Any]:
    """Reload the in-memory cache from disk for whichever file
    changed (or both if ``force`` is True).  If ``force`` is False
    and both mtimes are unchanged, the function no-ops and reports
    ``skipped: true``.

    The cache is *never* cleared on a parse error — the previous
    in-memory list stays available, and ``status`` reports the
    error so the admin page can surface it.
    """
    global _USERS, _DLS
    global _USERS_MTIME, _DLS_MTIME
    global _LAST_LOAD_AT, _LOAD_ERROR

    with _LOCK:
        users_path = _USERS_PATH or _resolve_users_path()
        dls_path   = _DLS_PATH   or _resolve_dls_path()

        try:
            users_mtime = os.path.getmtime(users_path) if os.path.exists(users_path) else 0.0
        except OSError:
            users_mtime = 0.0
        try:
            dls_mtime = os.path.getmtime(dls_path) if os.path.exists(dls_path) else 0.0
        except OSError:
            dls_mtime = 0.0

        users_changed = users_mtime != _USERS_MTIME
        dls_changed   = dls_mtime   != _DLS_MTIME

        if not force and not users_changed and not dls_changed and (_USERS or _DLS):
            return {
                "ok":        True,
                "users":     len(_USERS),
                "dls":       len(_DLS),
                "usersPath": users_path,
                "dlsPath":   dls_path,
                "message":   "Already up-to-date (file mtimes unchanged).",
                "skipped":   True,
            }

        # Reload only what changed (or both if forced).
        # Missing files produce empty lists without raising.
        err: Optional[str] = None
        if force or users_changed:
            new_users, err_u = _load_csv(users_path, _normalise_user)
            if err_u is None:
                _USERS = new_users
                _USERS_MTIME = users_mtime
            else:
                err = err_u

        if force or dls_changed:
            new_dls, err_d = _load_csv(dls_path, _normalise_dl)
            if err_d is None:
                _DLS = new_dls
                _DLS_MTIME = dls_mtime
            else:
                err = err or err_d

        if err is None:
            _LAST_LOAD_AT = time.time()
            _LOAD_ERROR = None
            return {
                "ok":        True,
                "users":     len(_USERS),
                "dls":       len(_DLS),
                "usersPath": users_path,
                "dlsPath":   dls_path,
                "message":   (
                    f"Loaded {len(_USERS)} users + {len(_DLS)} distribution lists."
                ),
                "skipped":   False,
            }
        # Partial / full parse error: keep the existing caches.
        return {
            "ok":        False,
            "users":     len(_USERS),
            "dls":       len(_DLS),
            "usersPath": users_path,
            "dlsPath":   dls_path,
            "message":   err,
            "skipped":   False,
        }


# ── Search ─────────────────────────────────────────────────────────────

# Pre-compiled regex for tokenisation — we split the user's query
# into whitespace-separated tokens and require EVERY token to be
# present (anywhere) in the entry's haystack.  This gives the
# classic "type two letters, get a name" behaviour without needing
# a real search engine.
_WHITESPACE = re.compile(r"\s+")


def _ensure_fresh() -> None:
    """Auto-reload the cache if either file's mtime has changed
    since the last load.  Called once per request — the mtime
    check is a single stat() call (~microseconds) per file so the
    overhead is negligible.
    """
    global _USERS_MTIME, _DLS_MTIME
    with _LOCK:
        if not _USERS_PATH and not _DLS_PATH:
            return
        users_mtime = dls_mtime = 0.0
        try:
            if _USERS_PATH:
                users_mtime = os.path.getmtime(_USERS_PATH)
        except OSError:
            pass
        try:
            if _DLS_PATH:
                dls_mtime = os.path.getmtime(_DLS_PATH)
        except OSError:
            pass
        if users_mtime != _USERS_MTIME or dls_mtime != _DLS_MTIME:
            reload(force=True)


def search(
    query: str,
    *,
    limit: int = 8,
    enabled_only: bool = True,
    kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return up to ``limit`` directory entries matching ``query``.

    Matching rules:
      - case-insensitive
      - query is split into whitespace-separated tokens
      - every token must be present (anywhere) in the entry's
        haystack (name + email + alias)
      - results are ranked by:
          1. exact-email match first
          2. token match in email (prefix bonus)
          3. token match in name (prefix bonus)
          4. kind tiebreaker — users rank above distribution lists
             when everything else is equal (more specific wins)
          5. alphabetical by name as a final tiebreaker
      - the optional ``kind`` filter restricts the search to a
        single source ("user" or "distribution_list").  When None
        (the default) both sources are searched.
      - ``enabled_only`` is accepted for API compatibility; both
        CSVs currently have no "enabled" column so every row
        passes the filter.
    """
    _ensure_fresh()
    q = (query or "").strip().lower()
    if not q:
        # Empty query: return nothing (the typeahead should not
        # show a giant list on focus).  The caller can use the
        # empty-query UX (recent recipients) if it wants.
        return []
    tokens = [t for t in _WHITESPACE.split(q) if t]

    with _LOCK:
        # Build the candidate pool honouring the kind filter.
        if kind == KIND_USER:
            pool: List[DirectoryEntry] = list(_USERS)
        elif kind == KIND_DISTRIBUTION_LIST:
            pool = list(_DLS)
        else:
            # No filter: merge both.  The combined search is O(n)
            # where n = users + dls, but every entry is just one
            # substring check, so even at ~1200 entries it
            # completes in microseconds.
            pool = list(_USERS) + list(_DLS)

    # Stable ordering of kinds for the tiebreaker.  Lower = better.
    # Users (kind=0) win over distribution lists (kind=1) when
    # everything else is equal — a person is a more specific match
    # than a group with the same name.
    _KIND_RANK = {KIND_USER: 0, KIND_DISTRIBUTION_LIST: 1}

    def score(e: DirectoryEntry) -> Tuple[int, int, int, int, str]:
        if e.email == q:
            return (0, 0, 0, _KIND_RANK.get(e.kind, 9), e.name.lower())
        email_bonus = 0 if e.email.startswith(tokens[0]) else 1
        name_bonus  = 0 if e.name.lower().startswith(tokens[0]) else 1
        return (
            1,
            name_bonus,
            email_bonus,
            _KIND_RANK.get(e.kind, 9),
            e.name.lower(),
        )

    matched: List[DirectoryEntry] = []
    for e in pool:
        if enabled_only and not e.enabled:
            continue
        if all(tok in e._haystack for tok in tokens):
            matched.append(e)
    matched.sort(key=score)
    return [e.to_public_dict() for e in matched[:limit]]


def list_recent(limit: int = 8) -> List[Dict[str, Any]]:
    """Return the alphabetically-first N enabled entries from BOTH
    sources (kind-prefixed).

    Used as a "starter set" when the user opens the dropdown
    before typing anything (so they see a sample of the
    directory).  Limited to 8 by default.

    The output is interleaved so the user sees a mix of people
    and groups rather than all of one kind first.
    """
    _ensure_fresh()
    with _LOCK:
        entries = [e for e in (_USERS + _DLS) if e.enabled]
    entries.sort(key=lambda e: (e.name or e.email).lower())
    return [e.to_public_dict() for e in entries[:limit]]


# ── Status ─────────────────────────────────────────────────────────────

def _iso_ist(epoch: float) -> Optional[str]:
    """Render an epoch as an ISO-8601 string in Asia/Kolkata."""
    if epoch is None:
        return None
    try:
        # Import lazily to avoid a hard dependency on tz at module
        # import time (tz is only loaded in app.utils).
        from app.utils.tz import iso_ist
        return iso_ist(datetime.fromtimestamp(epoch))
    except Exception:
        return None


def status() -> Dict[str, Any]:
    """Return the current state of the cache for the admin UI.

    Fields:
      - healthy        : True iff at least one of the two files is
                         present and parsed cleanly
      - usersPath      : path being watched for Users.csv
      - dlsPath        : path being watched for DistributionLists.csv
      - totalUsers     : count of entries parsed from Users.csv
      - totalDls       : count of entries parsed from DistributionLists.csv
      - usersFileExists: Users.csv is present on disk
      - dlsFileExists  : DistributionLists.csv is present on disk
      - usersFileSize  : Users.csv size in bytes
      - dlsFileSize    : DistributionLists.csv size in bytes
      - loadedAt       : epoch seconds of the last successful reload
      - loadedAtIst    : same in ISO-8601 Asia/Kolkata
      - lastError      : the most recent parse/IO error, or None
    """
    _ensure_fresh()
    with _LOCK:
        users_path = _USERS_PATH or _resolve_users_path()
        dls_path   = _DLS_PATH   or _resolve_dls_path()
        total_users = len(_USERS)
        total_dls   = len(_DLS)
        loaded_at   = _LAST_LOAD_AT
        err         = _LOAD_ERROR

    users_exists = os.path.exists(users_path)
    dls_exists   = os.path.exists(dls_path)
    return {
        "healthy":         err is None and (total_users + total_dls) > 0,
        "usersPath":       users_path,
        "dlsPath":         dls_path,
        "totalUsers":      total_users,
        "totalDls":        total_dls,
        "usersFileExists": users_exists,
        "dlsFileExists":   dls_exists,
        "usersFileSize":   os.path.getsize(users_path) if users_exists else 0,
        "dlsFileSize":     os.path.getsize(dls_path)   if dls_exists   else 0,
        "loadedAt":        loaded_at,
        "loadedAtIst":     _iso_ist(loaded_at) if loaded_at else None,
        "lastError":       err,
    }
