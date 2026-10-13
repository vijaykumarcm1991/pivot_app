"""
Encryption for secrets stored in the database (currently the SMTP
password), using Fernet (AES-128-CBC + HMAC-SHA256).

Key source, in order:
  1. APP_SECRET_KEY env var — any string; it is stretched to a Fernet key
     with SHA-256, so the same value always decrypts the same data.
  2. A key file `secret.key` next to the SQLite database (DB_PATH), created
     with 0600 permissions on first use. It lives on the same Docker volume
     as the database, so backups of that volume must keep both together.

Stored values look like "enc:v1:<token>". Values without the prefix are
treated as legacy plaintext and returned unchanged by `decrypt`.
"""
from __future__ import annotations

import base64
import hashlib
import os
import threading

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"
_lock = threading.Lock()
_fernet: Fernet | None = None


class SecretError(RuntimeError):
    """The stored secret can't be decrypted with the current key."""


def _key_file() -> str:
    from app.config.database import DB_PATH
    return os.path.join(os.path.dirname(DB_PATH), "secret.key")


def _load_key() -> bytes:
    env = os.environ.get("APP_SECRET_KEY", "").strip()
    if env:
        return base64.urlsafe_b64encode(hashlib.sha256(env.encode("utf-8")).digest())
    path = _key_file()
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def _get() -> Fernet:
    global _fernet
    with _lock:
        if _fernet is None:
            _fernet = Fernet(_load_key())
        return _fernet


def is_encrypted(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt(plain: str | None) -> str:
    if not plain:
        return ""
    if is_encrypted(plain):
        return plain
    return PREFIX + _get().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str:
    if not value:
        return ""
    if not is_encrypted(value):
        return value  # legacy plaintext
    try:
        return _get().decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretError(
            "The saved SMTP password can't be decrypted (the encryption key "
            "changed). Re-enter the password on the SMTP Settings page."
        ) from exc
