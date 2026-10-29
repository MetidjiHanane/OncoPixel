"""Password hashing, login lockout, session tokens and encryption at rest.

* Passwords: scrypt (stdlib) with a random per-user salt; constant-time comparison.
* Lockout: after repeated failures the account is locked for an exponentially growing time.
* Sessions: random bearer tokens held in memory with an idle timeout (one local user).
* Vault: Fernet (AES-128-CBC + HMAC-SHA256). The key lives in the OS keychain when the
  ``keyring`` package can reach one, otherwise in a ``0600`` file inside the data directory.
  Encrypted: patient fields and every image, mask and map file. Not encrypted: study dates,
  statuses and predicted classes (needed for search).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MAX_FAILED = 5
BASE_LOCK_SECONDS = 30
MAX_LOCK_SECONDS = 15 * 60
SESSION_IDLE_SECONDS = 8 * 60 * 60


class PasswordPolicyError(ValueError):
    pass


def check_password_policy(password: str) -> None:
    if len(password) < 8:
        raise PasswordPolicyError("password_too_short")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise PasswordPolicyError("password_needs_letter_and_digit")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        SCRYPT_N, SCRYPT_R, SCRYPT_P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        got = hashlib.scrypt(password.encode(), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


def lock_seconds_for(failed_attempts: int) -> float:
    """Lock duration after ``failed_attempts`` consecutive failures (0 below the limit)."""
    if failed_attempts < MAX_FAILED:
        return 0.0
    extra = failed_attempts - MAX_FAILED
    return float(min(BASE_LOCK_SECONDS * (2**extra), MAX_LOCK_SECONDS))


class SessionStore:
    """In-memory session tokens with idle expiry."""

    def __init__(self, idle_seconds: float = SESSION_IDLE_SECONDS):
        self._sessions: Dict[str, Tuple[str, float]] = {}
        self.idle_seconds = idle_seconds

    def create(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = (username, time.time())
        return token

    def validate(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        item = self._sessions.get(token)
        if not item:
            return None
        username, last = item
        now = time.time()
        if now - last > self.idle_seconds:
            self._sessions.pop(token, None)
            return None
        self._sessions[token] = (username, now)
        return username

    def revoke(self, token: Optional[str]) -> None:
        if token:
            self._sessions.pop(token, None)

    def clear(self) -> None:
        self._sessions.clear()


class Vault:
    """Symmetric encryption for data at rest."""

    SERVICE = "OncoPixel"
    ACCOUNT = "data-key"

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.key_source = "unknown"
        self._key = self._load_or_create_key()
        self._fernet = Fernet(self._key)

    def _load_or_create_key(self) -> bytes:
        env = os.environ.get("ONCOPIXEL_VAULT_KEY")
        if env:
            self.key_source = "environment"
            return env.encode()
        key_file = self.data_dir / "vault.key"
        if key_file.exists():
            self.key_source = "file"
            return key_file.read_bytes().strip()
        try:  # prefer the OS keychain when available (macOS Keychain, Windows Credential Locker)
            import keyring  # type: ignore

            if os.environ.get("ONCOPIXEL_DISABLE_KEYRING") != "1":
                stored = keyring.get_password(self.SERVICE, self.ACCOUNT)
                if stored:
                    self.key_source = "keychain"
                    return stored.encode()
                key = Fernet.generate_key()
                keyring.set_password(self.SERVICE, self.ACCOUNT, key.decode())
                self.key_source = "keychain"
                return key
        except Exception:
            pass
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        self.key_source = "file"
        return key

    def key_bytes(self) -> bytes:
        """Raw key, needed to build an encrypted backup. Never log or return it over the API."""
        return self._key

    def encrypt(self, data: bytes) -> bytes:
        return self._fernet.encrypt(data)

    def decrypt(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise ValueError("Cannot decrypt data: the vault key does not match this data directory") from exc

    def encrypt_text(self, text: Optional[str]) -> Optional[bytes]:
        if text is None:
            return None
        return self.encrypt(text.encode("utf-8"))

    def decrypt_text(self, token: Optional[bytes]) -> Optional[str]:
        if token is None:
            return None
        return self.decrypt(bytes(token)).decode("utf-8")


def derive_backup_key(passphrase: str, salt: bytes) -> bytes:
    raw = hashlib.scrypt(passphrase.encode(), salt=salt, n=2**15, r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024)
    return base64.urlsafe_b64encode(raw)
