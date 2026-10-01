#!/usr/bin/env python3
"""Offline SHA-512 verify against Proton index fixtures (no live network)."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop import cli_verify, config  # noqa: E402

# Fixture digests are local test vectors, not Proton production checksums.
_FIXTURE_OK = "a" * 128
_FIXTURE_OTHER = "b" * 128

_FIXTURE_HTML = """
<!DOCTYPE html><html><body>
<table><tbody>
<tr>
  <td>linux/x64</td>
  <td><a href="https://proton.me/download/drive/cli/0.0.0/linux-x64/proton-drive">url</a></td>
  <td><code>{ok}</code></td>
</tr>
<tr>
  <td>linux/arm64</td>
  <td><a href="https://proton.me/download/drive/cli/0.0.0/linux-arm64/proton-drive">url</a></td>
  <td><code>{other}</code></td>
</tr>
<tr>
  <td>macos/x64</td>
  <td><a href="https://proton.me/download/drive/cli/0.0.0/darwin-x64/proton-drive">url</a></td>
  <td><code>{mac}</code></td>
</tr>
</tbody></table>
</body></html>
""".format(ok=_FIXTURE_OK, other=_FIXTURE_OTHER, mac="c" * 128)

_FIXTURE_MD = """
| Platform | URL | Checksum (SHA-512) |
| --- | --- | --- |
| linux/x64 | https://proton.me/download/drive/cli/0.0.0/linux-x64/proton-drive | `{ok}` |
| linux/arm64 | https://proton.me/download/drive/cli/0.0.0/linux-arm64/proton-drive | `{other}` |
""".format(ok=_FIXTURE_OK, other=_FIXTURE_OTHER)


def _write_binary(folder: Path, data: bytes = b"proton-drive-fixture\n") -> Path:
    path = folder / "proton-drive"
    path.write_bytes(data)
    path.chmod(0o755)
    return path


def test_parse_html_and_markdown_linux_only() -> None:
    html = cli_verify.parse_published_checksums(_FIXTURE_HTML)
    assert html["linux/x64"] == _FIXTURE_OK
    assert html["linux/arm64"] == _FIXTURE_OTHER
    assert "macos/x64" not in html
    md = cli_verify.parse_published_checksums(_FIXTURE_MD)
    assert md["linux/x64"] == _FIXTURE_OK
    assert len(md) == 2
    print("parse ok")


def test_verify_ok_and_cache_skips_refetch(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-desktop-cli-verify-ok")
    folder.mkdir(parents=True, exist_ok=True)
    binary = _write_binary(folder, b"match-me")
    # Force digest to the fixture by patching sha512_file.
    original_dir = config.CONFIG_DIR
    config.CONFIG_DIR = folder
    fetches: list[str] = []

    def fake_fetch(url: str) -> str:
        fetches.append(url)
        return _FIXTURE_HTML

    try:
        with mock.patch.object(cli_verify, "sha512_file", return_value=_FIXTURE_OK):
            first = cli_verify.verify_proton_drive_binary(
                binary,
                fetch_html=fake_fetch,
                ttl_seconds=3600,
            )
            assert first.status == "ok"
            assert first.matched_platform == "linux/x64"
            assert first.should_warn is False
            assert first.from_cache is False
            assert len(fetches) == 1

            second = cli_verify.verify_proton_drive_binary(
                binary,
                fetch_html=fake_fetch,
                ttl_seconds=3600,
            )
            assert second.status == "ok"
            assert second.from_cache is True
            assert second.should_warn is False
            assert len(fetches) == 1
    finally:
        config.CONFIG_DIR = original_dir
    print("ok+cache ok")


def test_verify_mismatch_warns_once(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-desktop-cli-verify-mismatch")
    folder.mkdir(parents=True, exist_ok=True)
    binary = _write_binary(folder, b"tampered")
    original_dir = config.CONFIG_DIR
    config.CONFIG_DIR = folder
    bad = "d" * 128
    fetches = 0

    def fake_fetch(_url: str) -> str:
        nonlocal fetches
        fetches += 1
        return _FIXTURE_HTML

    try:
        with mock.patch.object(cli_verify, "sha512_file", return_value=bad):
            first = cli_verify.verify_proton_drive_binary(binary, fetch_html=fake_fetch)
            assert first.status == "mismatch"
            assert first.should_warn is True
            assert first.published_count == 2
            body = cli_verify.mismatch_warning_body(first)
            assert "will not replace" in body
            assert first.path in body

            second = cli_verify.verify_proton_drive_binary(binary, fetch_html=fake_fetch)
            assert second.status == "mismatch"
            assert second.should_warn is False
            assert second.from_cache is True
            assert fetches == 1
    finally:
        config.CONFIG_DIR = original_dir
    print("mismatch ok")


def test_fetch_failure_degrades_without_warn(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-desktop-cli-verify-offline")
    folder.mkdir(parents=True, exist_ok=True)
    binary = _write_binary(folder)
    original_dir = config.CONFIG_DIR
    config.CONFIG_DIR = folder

    def boom(_url: str) -> str:
        raise TimeoutError("offline fixture")

    try:
        result = cli_verify.verify_proton_drive_binary(binary, fetch_html=boom)
        assert result.status == "unavailable"
        assert result.should_warn is False
        assert "could not fetch" in result.detail
        # Cached unavailable short-circuits a second attempt.
        again = cli_verify.verify_proton_drive_binary(binary, fetch_html=boom)
        assert again.from_cache is True
        assert again.should_warn is False
    finally:
        config.CONFIG_DIR = original_dir
    print("offline ok")


def test_real_sha512_matches_local_file(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-desktop-cli-verify-hash")
    folder.mkdir(parents=True, exist_ok=True)
    data = b"hash-me-please\n"
    binary = _write_binary(folder, data)
    expected = hashlib.sha512(data).hexdigest()
    assert cli_verify.sha512_file(binary) == expected
    print("hash ok")


def test_index_url_is_proton_download_page() -> None:
    from proton_drive_desktop.paths import CLI_DOWNLOAD_URL

    assert CLI_DOWNLOAD_URL == "https://proton.me/download/drive/cli/index.html"
    assert cli_verify.CLI_DOWNLOAD_URL == CLI_DOWNLOAD_URL
    print("url ok")


if __name__ == "__main__":
    test_parse_html_and_markdown_linux_only()
    test_verify_ok_and_cache_skips_refetch()
    test_verify_mismatch_warns_once()
    test_fetch_failure_degrades_without_warn()
    test_real_sha512_matches_local_file()
    test_index_url_is_proton_download_page()
    print("cli_verify checks passed")
