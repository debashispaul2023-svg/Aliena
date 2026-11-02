"""Secure download manager and verification core for Jarvis.

Phase B only: streaming download, path safety, size limits, SHA-256,
redirect safety, and integrity checks. Does not extract archives,
install packages, or execute downloaded content.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import socket
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests

# Default max size: 50 MiB (configurable)
DEFAULT_MAX_BYTES = 50 * 1024 * 1024
CHUNK_SIZE = 64 * 1024
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0
DEFAULT_RETRIES = 2

# Schemes allowed for production downloads
ALLOWED_SCHEMES = frozenset({"http", "https"})


class DownloadError(Exception):
    """Structured download/verification failure."""

    def __init__(self, message: str, *, code: str = "error") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class DownloadResult:
    success: bool
    path: Optional[str] = None
    original_url: str = ""
    final_url: str = ""
    size: int = 0
    sha256: str = ""
    content_type: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    cancelled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "path": self.path,
            "original_url": self.original_url,
            "final_url": self.final_url,
            "size": self.size,
            "sha256": self.sha256,
            "content_type": self.content_type,
            "error": self.error,
            "error_code": self.error_code,
            "cancelled": self.cancelled,
            "metadata": dict(self.metadata),
        }


@dataclass
class VerificationResult:
    ok: bool
    path: str
    exists: bool = False
    size: int = 0
    sha256: str = ""
    checksum_match: Optional[bool] = None  # None if no expected hash supplied
    type_match: Optional[bool] = None
    authenticity_verified: bool = False  # True only if trusted checksum matched
    errors: list[str] = field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# Path / filename safety
# ---------------------------------------------------------------------------

_UNSAFE_NAME = re.compile(r'[<>:"|?*\x00-\x1f]')
_TRAVERSAL = re.compile(r"(^|[\\/])\.\.([\\/]|$)")


def safe_filename(name: str, default: str = "download.bin") -> str:
    """Sanitize a basename; reject traversal and reserved characters."""
    if not name or not str(name).strip():
        return default
    base = os.path.basename(str(name).replace("\\", "/"))
    base = base.strip().strip(".")
    if not base or base in (".", ".."):
        return default
    if _TRAVERSAL.search(base) or ".." in base:
        raise DownloadError("Unsafe filename (path traversal)", code="unsafe_filename")
    base = _UNSAFE_NAME.sub("_", base)
    if not base or base in (".", ".."):
        return default
    # Windows reserved device names
    stem = base.split(".")[0].upper()
    if stem in {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }:
        base = f"_{base}"
    return base[:200]


def resolve_under_root(root: Path, relative: str | Path) -> Path:
    """Resolve path and ensure it stays under root (no symlink escape)."""
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise DownloadError(
            f"Path escapes resource root: {candidate}",
            code="path_escape",
        ) from exc
    return candidate


# ---------------------------------------------------------------------------
# URL / redirect safety
# ---------------------------------------------------------------------------

def _is_private_or_local(host: str) -> bool:
    """Return True if host resolves to loopback/private/link-local/unspecified."""
    if not host:
        return True
    host_l = host.lower().strip("[]")
    if host_l in {"localhost", "0.0.0.0"}:
        return True
    try:
        infos = socket.getaddrinfo(host_l, None)
    except socket.gaierror:
        # Unresolvable — treat as unsafe for SSRF purposes
        return True
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def validate_url(
    url: str,
    *,
    allow_private: bool = False,
) -> str:
    """Validate scheme, reject credentials and (by default) private targets."""
    if not url or not isinstance(url, str):
        raise DownloadError("Empty or invalid URL", code="invalid_url")
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise DownloadError(
            f"Unsupported URL scheme: {scheme or '(none)'}",
            code="bad_scheme",
        )
    if parsed.username or parsed.password:
        raise DownloadError("URLs with embedded credentials are not allowed", code="credentials_in_url")
    host = parsed.hostname or ""
    if not host:
        raise DownloadError("URL missing host", code="invalid_url")
    if not allow_private and _is_private_or_local(host):
        raise DownloadError(
            f"Refusing download from private/local host: {host}",
            code="private_host",
        )
    return url.strip()


# Simple magic-byte signatures for optional type checks
_SIGNATURES: dict[str, list[bytes]] = {
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif": [b"GIF87a", b"GIF89a"],
    "pdf": [b"%PDF"],
    "zip": [b"PK\x03\x04", b"PK\x05\x06"],
    "gz": [b"\x1f\x8b"],
    "json": [],  # text; checked loosely
    "txt": [],
}


def check_file_signature(path: Path, expected_type: str) -> Optional[bool]:
    """Return True/False if we can check, None if type is unknown/text."""
    key = expected_type.lower().lstrip(".")
    sigs = _SIGNATURES.get(key)
    if sigs is None:
        return None
    if not sigs:
        return True  # no binary signature required
    data = path.read_bytes()[:16]
    return any(data.startswith(s) for s in sigs)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def sha256_file(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify_file(
    path: str | Path,
    *,
    expected_sha256: Optional[str] = None,
    expected_size: Optional[int] = None,
    require_nonzero: bool = True,
    expected_type: Optional[str] = None,
) -> VerificationResult:
    """Verify a local file. authenticity_verified only if trusted checksum matches."""
    p = Path(path)
    errors: list[str] = []
    exists = p.is_file()
    if not exists:
        return VerificationResult(
            ok=False,
            path=str(p),
            exists=False,
            errors=["File does not exist"],
        )
    size = p.stat().st_size
    if require_nonzero and size == 0:
        errors.append("File is empty")
    if expected_size is not None and size != expected_size:
        errors.append(f"Size mismatch: actual={size} expected={expected_size}")

    digest = sha256_file(p)
    checksum_match: Optional[bool] = None
    authenticity = False
    if expected_sha256:
        checksum_match = digest.lower() == expected_sha256.lower()
        if not checksum_match:
            errors.append("SHA-256 mismatch")
        else:
            authenticity = True

    type_match: Optional[bool] = None
    if expected_type:
        type_match = check_file_signature(p, expected_type)
        if type_match is False:
            errors.append(f"File signature does not match expected type {expected_type}")

    return VerificationResult(
        ok=len(errors) == 0,
        path=str(p),
        exists=True,
        size=size,
        sha256=digest,
        checksum_match=checksum_match,
        type_match=type_match,
        authenticity_verified=authenticity,
        errors=errors,
        notes=(
            "SHA-256 calculated for integrity tracking; "
            "authenticity_verified only when a trusted checksum matched."
        ),
    )


# ---------------------------------------------------------------------------
# Download Manager
# ---------------------------------------------------------------------------

class DownloadManager:
    """Stream downloads into a configured resource root with safety checks."""

    def __init__(
        self,
        resource_root: str | Path,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        max_retries: int = DEFAULT_RETRIES,
        allow_private_hosts: bool = False,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.resource_root = Path(resource_root).resolve()
        self.resource_root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max(1, int(max_bytes))
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_retries = max(0, int(max_retries))
        self.allow_private_hosts = allow_private_hosts
        self._session = session or requests.Session()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def reset_cancel(self) -> None:
        self._cancel.clear()

    def _destination(self, filename: str, subdir: str = "") -> Path:
        name = safe_filename(filename)
        if subdir:
            # subdir must be relative and safe
            parts = Path(subdir.replace("\\", "/")).parts
            if any(p in ("", "..") or p.startswith("/") for p in parts):
                raise DownloadError("Unsafe subdirectory", code="unsafe_filename")
            dest_dir = resolve_under_root(self.resource_root, Path(*parts))
        else:
            dest_dir = self.resource_root
        dest_dir.mkdir(parents=True, exist_ok=True)
        return resolve_under_root(dest_dir, name)

    def download(
        self,
        url: str,
        *,
        filename: Optional[str] = None,
        subdir: str = "",
        expected_sha256: Optional[str] = None,
        expected_size: Optional[int] = None,
        expected_type: Optional[str] = None,
        overwrite: bool = False,
    ) -> DownloadResult:
        """Download URL into resource_root. Does not install or execute the file."""
        self.reset_cancel()
        original_url = url
        try:
            validate_url(url, allow_private=self.allow_private_hosts)
        except DownloadError as exc:
            return DownloadResult(
                success=False,
                original_url=original_url,
                error=exc.message,
                error_code=exc.code,
            )

        # Derive filename from URL if needed
        if not filename:
            path_part = urlparse(url).path
            filename = os.path.basename(path_part) or "download.bin"
        try:
            dest = self._destination(filename, subdir=subdir)
        except DownloadError as exc:
            return DownloadResult(
                success=False,
                original_url=original_url,
                error=exc.message,
                error_code=exc.code,
            )

        if dest.exists() and not overwrite:
            return DownloadResult(
                success=False,
                path=str(dest),
                original_url=original_url,
                error="Destination exists; pass overwrite=True to replace",
                error_code="exists",
            )

        # Exclusive claim lock so concurrent downloads to the same dest collide safely
        lock_path = dest.parent / (dest.name + ".jarvis.lock")  # cleaned in finally
        try:
            lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(lock_fd)
        except FileExistsError:
            return DownloadResult(
                success=False,
                path=str(dest),
                original_url=original_url,
                error="Another download is in progress for this destination",
                error_code="locked",
            )
        except OSError as exc:
            return DownloadResult(
                success=False,
                original_url=original_url,
                error=f"Could not claim download lock: {exc}",
                error_code="fs_error",
            )

        # Temp file on same filesystem for atomic replace
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".jarvis_dl_",
            suffix=".partial",
            dir=str(dest.parent),
        )
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)

        hasher = hashlib.sha256()
        total = 0
        final_url = original_url
        content_type = None
        last_error: Optional[str] = None
        error_code = "download_failed"

        try:
            for attempt in range(self.max_retries + 1):
                if self._cancel.is_set():
                    raise DownloadError("Download cancelled", code="cancelled")
                try:
                    with self._session.get(
                        url,
                        stream=True,
                        timeout=(self.connect_timeout, self.read_timeout),
                        allow_redirects=True,
                    ) as resp:
                        final_url = str(resp.url or url)
                        # Validate final URL after redirects
                        try:
                            validate_url(final_url, allow_private=self.allow_private_hosts)
                        except DownloadError as exc:
                            raise DownloadError(
                                f"Redirect target rejected: {exc.message}",
                                code="bad_redirect",
                            ) from exc

                        if resp.status_code >= 400:
                            raise DownloadError(
                                f"HTTP {resp.status_code}",
                                code=f"http_{resp.status_code}",
                            )

                        content_type = resp.headers.get("Content-Type")
                        # Content-Length pre-check when present
                        cl = resp.headers.get("Content-Length")
                        if cl is not None:
                            try:
                                if int(cl) > self.max_bytes:
                                    raise DownloadError(
                                        f"Content-Length {cl} exceeds max_bytes {self.max_bytes}",
                                        code="size_limit",
                                    )
                            except ValueError:
                                pass

                        hasher = hashlib.sha256()
                        total = 0
                        with open(tmp_path, "wb") as out:
                            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                                if self._cancel.is_set():
                                    raise DownloadError("Download cancelled", code="cancelled")
                                if not chunk:
                                    continue
                                total += len(chunk)
                                if total > self.max_bytes:
                                    raise DownloadError(
                                        f"Download exceeded max_bytes ({self.max_bytes})",
                                        code="size_limit",
                                    )
                                out.write(chunk)
                                hasher.update(chunk)

                        if total == 0:
                            raise DownloadError("Empty response body", code="empty")

                        # Success path for this attempt
                        digest = hasher.hexdigest()
                        if expected_sha256 and digest.lower() != expected_sha256.lower():
                            raise DownloadError("SHA-256 mismatch after download", code="checksum")
                        if expected_size is not None and total != expected_size:
                            raise DownloadError(
                                f"Size mismatch after download: {total} != {expected_size}",
                                code="size_mismatch",
                            )

                        # Type check on temp file
                        if expected_type:
                            tm = check_file_signature(tmp_path, expected_type)
                            if tm is False:
                                raise DownloadError(
                                    f"File signature mismatch for type {expected_type}",
                                    code="type_mismatch",
                                )

                        # Atomic move into place
                        if dest.exists() and overwrite:
                            dest.unlink()
                        os.replace(str(tmp_path), str(dest))
                        tmp_path = Path()  # moved

                        return DownloadResult(
                            success=True,
                            path=str(dest),
                            original_url=original_url,
                            final_url=final_url,
                            size=total,
                            sha256=digest,
                            content_type=content_type,
                            metadata={
                                "attempts": attempt + 1,
                                "authenticity_verified": bool(
                                    expected_sha256
                                    and digest.lower() == expected_sha256.lower()
                                ),
                            },
                        )
                except DownloadError as exc:
                    last_error = exc.message
                    error_code = exc.code
                    if exc.code in {"cancelled", "size_limit", "bad_redirect", "checksum", "type_mismatch", "empty"}:
                        break  # non-retryable
                    if attempt >= self.max_retries:
                        break
                    continue
                except requests.Timeout as exc:
                    last_error = f"Timeout: {exc}"
                    error_code = "timeout"
                    if attempt >= self.max_retries:
                        break
                    continue
                except requests.RequestException as exc:
                    last_error = f"Network error: {exc}"
                    error_code = "network"
                    if attempt >= self.max_retries:
                        break
                    continue
                except OSError as exc:
                    last_error = f"Filesystem error: {exc}"
                    error_code = "fs_error"
                    break
        finally:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            try:
                if lock_path.exists():
                    lock_path.unlink()
            except OSError:
                pass

        return DownloadResult(
            success=False,
            original_url=original_url,
            final_url=final_url,
            size=total,
            sha256=hasher.hexdigest() if total else "",
            content_type=content_type,
            error=last_error or "Download failed",
            error_code=error_code,
            cancelled=(error_code == "cancelled"),
        )
