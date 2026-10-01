"""Verify the on-disk ``proton-drive`` binary against Proton's published SHA-512.

Checksums are fetched live from Proton's CLI download index
(``https://proton.me/download/drive/cli/index.html``). This module never
downloads or replaces the binary — callers only warn on mismatch.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import CONFIG_DIR
from .paths import CLI_DOWNLOAD_URL

# Re-check the same path+digest at most once per day (avoids Settings/sync spam).
CACHE_TTL_SECONDS = 24 * 60 * 60
# When the index cannot be fetched, back off briefly before retrying.
FETCH_FAIL_TTL_SECONDS = 60 * 60
FETCH_TIMEOUT_SECONDS = 15

_CACHE_NAME = "cli-verify-cache.json"
_HEX_SHA512 = re.compile(r"^[0-9a-fA-F]{128}$")
# Official index rows: <td>linux/x64</td> … <td><code>…128 hex…</code></td>
_ROW_RE = re.compile(
    r"<td>\s*([^<]+?)\s*</td>\s*"
    r"<td>\s*(?:<a[^>]*>[^<]*</a>|[^<]+)\s*</td>\s*"
    r"<td>\s*<code>\s*([0-9a-fA-F]{128})\s*</code>\s*</td>",
    re.IGNORECASE | re.DOTALL,
)
# Markdown / plain tables used in tests and some doc mirrors.
_MD_ROW_RE = re.compile(
    r"\|\s*(linux/[^\s|]+)\s*\|\s*https?://[^\s|]+\s*\|\s*`?([0-9a-fA-F]{128})`?\s*\|",
    re.IGNORECASE,
)

FetchHtml = Callable[[str], str]


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of one verification attempt (or a fresh cache hit)."""

    status: str  # ok | mismatch | unavailable | missing | error
    path: str
    digest: str
    matched_platform: str
    published_count: int
    detail: str
    should_warn: bool
    from_cache: bool


def verify_cache_path() -> Path:
    return CONFIG_DIR / _CACHE_NAME


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha512_file(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def parse_published_checksums(text: str) -> dict[str, str]:
    """Parse Proton's CLI index HTML (or a markdown table fixture) into platform→sha512."""
    found: dict[str, str] = {}
    for match in _ROW_RE.finditer(text or ""):
        platform = match.group(1).strip()
        digest = match.group(2).strip().lower()
        if platform.lower().startswith("linux/") and _HEX_SHA512.fullmatch(digest):
            found[platform] = digest
    if not found:
        for match in _MD_ROW_RE.finditer(text or ""):
            platform = match.group(1).strip()
            digest = match.group(2).strip().lower()
            if _HEX_SHA512.fullmatch(digest):
                found[platform] = digest
    return found


def fetch_checksum_index(
    url: str = CLI_DOWNLOAD_URL,
    *,
    timeout: float = FETCH_TIMEOUT_SECONDS,
) -> str:
    """Download Proton's published CLI index HTML. Raises on network/HTTP failure."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "proton-drive-desktop/cli-verify",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — fixed Proton URL
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _load_cache() -> dict[str, Any]:
    path = verify_cache_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_cache(payload: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    verify_cache_path().write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _age_seconds(iso: str) -> float | None:
    text = str(iso or "").strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when.astimezone(timezone.utc)).total_seconds()


def _cache_hit(cache: dict[str, Any], path: str, digest: str, *, ttl: int) -> VerifyResult | None:
    if str(cache.get("path") or "") != path:
        return None
    if str(cache.get("digest") or "").lower() != digest.lower():
        return None
    status = str(cache.get("status") or "")
    if status not in {"ok", "mismatch", "unavailable", "error"}:
        return None
    age = _age_seconds(str(cache.get("checked_at") or ""))
    if age is None:
        return None
    limit = FETCH_FAIL_TTL_SECONDS if status in {"unavailable", "error"} else ttl
    if age >= limit:
        return None
    return VerifyResult(
        status=status,
        path=path,
        digest=digest.lower(),
        matched_platform=str(cache.get("matched_platform") or ""),
        published_count=int(cache.get("published_count") or 0),
        detail=str(cache.get("detail") or ""),
        should_warn=False,
        from_cache=True,
    )


def _resolve_binary(binary: str | Path | None) -> Path | None:
    if binary is not None:
        path = Path(binary).expanduser()
        return path if path.is_file() else None
    try:
        from .cli import find_binary

        return Path(find_binary())
    except Exception:
        return None


def verify_proton_drive_binary(
    binary: str | Path | None = None,
    *,
    force: bool = False,
    ttl_seconds: int = CACHE_TTL_SECONDS,
    index_url: str = CLI_DOWNLOAD_URL,
    fetch_html: FetchHtml | None = None,
) -> VerifyResult:
    """Hash the CLI and compare against Proton's published Linux SHA-512 values.

    On mismatch, ``should_warn`` is True only when this path+digest was not
    already checked within ``ttl_seconds`` (callers must not auto-replace).
    Network/index failures set status ``unavailable`` and do not warn.
    """
    path = _resolve_binary(binary)
    if path is None:
        return VerifyResult(
            status="missing",
            path=str(binary or ""),
            digest="",
            matched_platform="",
            published_count=0,
            detail="proton-drive binary not found",
            should_warn=False,
            from_cache=False,
        )
    path_text = str(path.resolve()) if path.exists() else str(path)
    try:
        digest = sha512_file(path)
    except OSError as exc:
        return VerifyResult(
            status="error",
            path=path_text,
            digest="",
            matched_platform="",
            published_count=0,
            detail=str(exc),
            should_warn=False,
            from_cache=False,
        )

    if not force:
        hit = _cache_hit(_load_cache(), path_text, digest, ttl=ttl_seconds)
        if hit is not None:
            return hit

    fetcher = fetch_html or fetch_checksum_index
    try:
        html = fetcher(index_url)
        published = parse_published_checksums(html)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        detail = f"could not fetch Proton CLI checksums: {exc}"
        result = VerifyResult(
            status="unavailable",
            path=path_text,
            digest=digest,
            matched_platform="",
            published_count=0,
            detail=detail,
            should_warn=False,
            from_cache=False,
        )
        _save_cache(
            {
                "path": path_text,
                "digest": digest,
                "status": result.status,
                "matched_platform": "",
                "published_count": 0,
                "detail": detail,
                "checked_at": utc_now(),
                "index_url": index_url,
            }
        )
        return result

    if not published:
        detail = "Proton CLI index had no linux SHA-512 rows"
        result = VerifyResult(
            status="unavailable",
            path=path_text,
            digest=digest,
            matched_platform="",
            published_count=0,
            detail=detail,
            should_warn=False,
            from_cache=False,
        )
        _save_cache(
            {
                "path": path_text,
                "digest": digest,
                "status": result.status,
                "matched_platform": "",
                "published_count": 0,
                "detail": detail,
                "checked_at": utc_now(),
                "index_url": index_url,
            }
        )
        return result

    digest_l = digest.lower()
    matched = ""
    for platform, published_digest in published.items():
        if published_digest == digest_l:
            matched = platform
            break

    if matched:
        status = "ok"
        detail = f"matches Proton published SHA-512 for {matched}"
        should_warn = False
    else:
        status = "mismatch"
        detail = (
            f"SHA-512 {digest_l[:16]}… does not match any of "
            f"{len(published)} Proton linux checksums"
        )
        should_warn = True

    result = VerifyResult(
        status=status,
        path=path_text,
        digest=digest_l,
        matched_platform=matched,
        published_count=len(published),
        detail=detail,
        should_warn=should_warn,
        from_cache=False,
    )
    _save_cache(
        {
            "path": path_text,
            "digest": digest_l,
            "status": status,
            "matched_platform": matched,
            "published_count": len(published),
            "detail": detail,
            "checked_at": utc_now(),
            "index_url": index_url,
        }
    )
    return result


def mismatch_warning_body(result: VerifyResult) -> str:
    """English body text for dialogs / notify-send (callers wrap with gettext)."""
    short = (result.digest[:16] + "…") if len(result.digest) >= 16 else (result.digest or "?")
    return (
        f"The proton-drive binary at {result.path} does not match any SHA-512 "
        f"published by Proton for Linux (digest {short}). This app will not replace it. "
        f"Download a fresh CLI from proton.me if you did not build it yourself."
    )
