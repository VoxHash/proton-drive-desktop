#!/usr/bin/env python3
"""Checks that do not call Proton APIs: local GUI config and install metadata."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proton_drive_desktop import config  # noqa: E402
from proton_drive_desktop.paths import APP_ICON_NAME, HELP_URL, icon_png, icon_svg  # noqa: E402


def test_config_roundtrip(tmp_path: Path | None = None) -> None:
    folder = tmp_path or Path("/tmp/proton-drive-desktop-config-test")
    folder.mkdir(parents=True, exist_ok=True)
    original_dir, original_path = config.CONFIG_DIR, config.CONFIG_PATH
    config.CONFIG_DIR = folder
    config.CONFIG_PATH = folder / "gui.json"
    try:
        config.save({"theme": "light", "language": "en", "download_folder": str(folder), "cli_path": "", "autostart": False, "sync_folder": str(folder), "sync_enabled": False})
        loaded = config.load()
        assert loaded["theme"] == "light"
        assert loaded["language"] == "en"
        assert loaded["download_folder"] == str(folder)
        assert loaded["sync_folder"] == str(folder)
        assert loaded["sync_enabled"] is False
    finally:
        config.CONFIG_DIR = original_dir
        config.CONFIG_PATH = original_path


def test_official_icon_installed() -> None:
    svg = icon_svg()
    assert svg.is_file(), svg
    text = svg.read_text(encoding="utf-8")
    assert "ProtonDriveApps/android-drive" in text
    assert "6D4AFF" in text
    assert icon_png(32).is_file()
    assert icon_png(48).is_file()
    desktop = (ROOT / "data" / f"{APP_ICON_NAME}.desktop").read_text(encoding="utf-8")
    assert f"Icon={APP_ICON_NAME}" in desktop
    assert "folder-remote" not in desktop
    assert "Name=Proton Drive" in desktop
    assert "Categories=Network;FileTransfer;GTK;" in desktop
    assert "StartupWMClass=io.github.voxhash.ProtonDriveDesktop" in desktop
    assert "Exec=proton-drive-desktop" in desktop
    metainfo = (ROOT / "data" / f"{APP_ICON_NAME}.metainfo.xml").read_text(encoding="utf-8")
    assert APP_ICON_NAME in metainfo
    assert HELP_URL in metainfo
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "user-install" in makefile
    assert "user-uninstall" in makefile
    assert "msgfmt" in makefile
    assert "LOCALES := en ru zh_CN ar it pt es ko ja" in makefile
    assert "locale/$$lang/LC_MESSAGES" in makefile
    potfiles = (ROOT / "po" / "POTFILES.in").read_text(encoding="utf-8")
    assert "proton_drive_desktop/app.py" in potfiles
    en_po = (ROOT / "po" / "en.po").read_text(encoding="utf-8")
    assert 'msgid "Settings"' in en_po
    assert 'msgstr "Settings"' in en_po
    for code in ("ru", "zh_CN", "ar", "it", "pt", "es", "ko", "ja"):
        po_text = (ROOT / "po" / f"{code}.po").read_text(encoding="utf-8")
        assert f"Language: {code}" in po_text
        assert 'msgid "Settings"' in po_text
    pkgbuild = (ROOT / "packaging" / "arch" / "PKGBUILD").read_text(encoding="utf-8")
    assert "proton-drive-desktop" in pkgbuild


def test_distribution_kit() -> None:
    """Release tarball, AppImage recipe, and install.sh are present and wired."""
    install_sh = ROOT / "install.sh"
    assert install_sh.is_file(), install_sh
    install_text = install_sh.read_text(encoding="utf-8")
    assert "CLI_INDEX_URL" in install_text
    assert "proton.me/download/drive/cli/index.html" in install_text
    assert "sha512" in install_text.lower()
    assert "--skip-cli" in install_text
    assert "--uninstall" in install_text
    assert "scripts/uninstall.sh" in install_text

    uninstall_sh = ROOT / "scripts" / "uninstall.sh"
    assert uninstall_sh.is_file(), uninstall_sh
    uninstall_text = uninstall_sh.read_text(encoding="utf-8")
    assert "--purge" in uninstall_text
    assert "--remove-cli" in uninstall_text
    assert "proton-drive-desktop" in uninstall_text
    assert "io.github.voxhash.ProtonDriveDesktop" in uninstall_text
    # Default must not wipe the official CLI or GUI config without flags.
    assert 'REMOVE_CLI=0' in uninstall_text or "REMOVE_CLI=0" in uninstall_text
    assert "PURGE=0" in uninstall_text
    assert "Leaving" in uninstall_text and "proton-drive" in uninstall_text

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "user-uninstall" in makefile
    assert "scripts/uninstall.sh" in makefile
    assert "TryExec" in makefile
    assert "\ndist:" in makefile or makefile.startswith("dist:") or "\ndist:\n" in makefile
    assert "appimage:" in makefile
    assert "deb:" in makefile
    assert "build-source-tarball.sh" in makefile
    assert "build-deb.sh" in makefile

    tarball_sh = ROOT / "scripts" / "build-source-tarball.sh"
    assert tarball_sh.is_file(), tarball_sh
    assert "SHA256SUMS" in tarball_sh.read_text(encoding="utf-8")

    appimage_sh = ROOT / "packaging" / "appimage" / "build-appimage.sh"
    assert appimage_sh.is_file(), appimage_sh
    appimage_text = appimage_sh.read_text(encoding="utf-8")
    assert "proton-drive" in appimage_text
    assert "Refusing to package" in appimage_text

    apprun = ROOT / "packaging" / "appimage" / "AppRun"
    assert apprun.is_file(), apprun
    assert "proton-drive-desktop" in apprun.read_text(encoding="utf-8")

    deb_sh = ROOT / "packaging" / "debian" / "build-deb.sh"
    assert deb_sh.is_file(), deb_sh
    deb_text = deb_sh.read_text(encoding="utf-8")
    assert "Refusing to package" in deb_text
    assert "SHA256SUMS" in deb_text
    assert "dpkg -r" in deb_text

    control_in = ROOT / "packaging" / "debian" / "control.in"
    assert control_in.is_file(), control_in
    control_text = control_in.read_text(encoding="utf-8")
    assert "Package: proton-drive-desktop" in control_text
    assert "Architecture: all" in control_text
    assert "python3-gi" in control_text
    assert "gir1.2-gtk-4.0" in control_text
    assert "gir1.2-adw-1" in control_text
    assert "does not ship the proton-drive" in control_text
    assert "@VERSION@" in control_text

    copyright_f = ROOT / "packaging" / "debian" / "copyright"
    assert copyright_f.is_file(), copyright_f
    copyright_text = copyright_f.read_text(encoding="utf-8")
    assert "MIT" in copyright_text
    assert "GPL-3.0-or-later" in copyright_text

    release_yml = ROOT / ".github" / "workflows" / "release.yml"
    assert release_yml.is_file(), release_yml
    release_text = release_yml.read_text(encoding="utf-8")
    assert "build-source-tarball.sh" in release_text
    assert "SHA256SUMS" in release_text
    assert "build-deb.sh" in release_text
    assert "proton-drive-desktop_*_all.deb" in release_text
    assert 'tags:' in release_text or '"v*"' in release_text


def test_deb_control_and_smoke_build() -> None:
    """Validate Debian control template and smoke-build a .deb when tooling exists."""
    import os
    import shutil
    import subprocess
    import tempfile

    control_in = (ROOT / "packaging" / "debian" / "control.in").read_text(encoding="utf-8")
    assert "Package: proton-drive-desktop" in control_in
    assert "Architecture: all" in control_in
    for dep in (
        "python3",
        "python3-gi",
        "gir1.2-gtk-4.0",
        "gir1.2-adw-1",
        "libgtk-4-1",
        "libadwaita-1-0",
        "libsecret-1-0",
        "hicolor-icon-theme",
    ):
        assert dep in control_in, dep
    # Must not declare a Depends on a Proton CLI binary package we do not ship.
    assert "proton-drive-cli" not in control_in
    assert "Depends:" in control_in and "proton-drive," not in control_in.replace("proton-drive-desktop", "")

    build_sh = ROOT / "packaging" / "debian" / "build-deb.sh"
    assert os.access(build_sh, os.X_OK) or build_sh.is_file()

    # Offline smoke: build when ar/tar/gzip/make/msgfmt are present (no dpkg-deb required).
    for tool in ("ar", "tar", "gzip", "make", "msgfmt", "md5sum", "sha256sum"):
        if shutil.which(tool) is None:
            print(f"skip deb smoke build: missing {tool}")
            return

    with tempfile.TemporaryDirectory(prefix="pdd-deb-") as tmp:
        env = os.environ.copy()
        env["DIST_DIR"] = tmp
        env["DEB_BUILD_DIR"] = str(Path(tmp) / "deb-build")
        proc = subprocess.run(
            ["bash", str(build_sh), "1.14.2"],
            cwd=str(ROOT),
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"make deb / build-deb.sh failed ({proc.returncode}):\n"
                f"{proc.stdout}\n{proc.stderr}"
            )
        deb_path = Path(tmp) / "proton-drive-desktop_1.14.2_all.deb"
        assert deb_path.is_file(), deb_path
        listing = subprocess.check_output(["ar", "t", str(deb_path)], text=True)
        assert "debian-binary" in listing
        # dpkg-deb on modern Ubuntu may emit .zst; ar+tar fallback uses .gz
        assert (
            "control.tar.gz" in listing
            or "control.tar.xz" in listing
            or "control.tar.zst" in listing
        ), listing
        assert (
            "data.tar.gz" in listing
            or "data.tar.xz" in listing
            or "data.tar.zst" in listing
        ), listing
        sums = (Path(tmp) / "SHA256SUMS").read_text(encoding="utf-8")
        assert "proton-drive-desktop_1.14.2_all.deb" in sums
        # Extract control and confirm key fields + no CLI binary in data
        extract_dir = Path(tmp) / "extract"
        extract_dir.mkdir()
        subprocess.check_call(["ar", "x", str(deb_path)], cwd=str(extract_dir))
        control_member = next(extract_dir.glob("control.tar.*"))
        data_member = next(extract_dir.glob("data.tar.*"))
        control_dir = extract_dir / "control"
        data_dir = extract_dir / "data"
        control_dir.mkdir()
        data_dir.mkdir()
        subprocess.check_call(["tar", "-xf", str(control_member), "-C", str(control_dir)])
        subprocess.check_call(["tar", "-xf", str(data_member), "-C", str(data_dir)])
        control = (control_dir / "control").read_text(encoding="utf-8")
        assert "Package: proton-drive-desktop" in control
        assert "Version: 1.14.2" in control
        assert "Architecture: all" in control
        assert "python3-gi" in control
        assert (data_dir / "usr" / "bin" / "proton-drive-desktop").is_file()
        assert not (data_dir / "usr" / "bin" / "proton-drive").exists()
        assert list(data_dir.rglob("proton-drive")) == []


if __name__ == "__main__":
    test_config_roundtrip()
    test_official_icon_installed()
    test_distribution_kit()
    test_deb_control_and_smoke_build()
    print("packaging checks passed")
