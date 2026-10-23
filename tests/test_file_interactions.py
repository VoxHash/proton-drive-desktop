#!/usr/bin/env python3
"""Offline checks for Delete/Backspace trash keys and context-click selection."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk  # noqa: E402

from proton_drive_desktop.app import (  # noqa: E402
    context_click_selection_action,
    key_requests_trash,
)


def test_key_requests_trash() -> None:
    assert key_requests_trash(Gdk.KEY_Delete)
    assert key_requests_trash(Gdk.KEY_KP_Delete)
    assert key_requests_trash(Gdk.KEY_BackSpace)
    assert not key_requests_trash(Gdk.KEY_Return)
    assert not key_requests_trash(Gdk.KEY_F2)
    assert not key_requests_trash(Gdk.KEY_Escape)
    assert not key_requests_trash(Gdk.KEY_a)


def test_context_click_selection_action() -> None:
    assert (
        context_click_selection_action(already_selected=False, ctrl_held=False) == "exclusive"
    )
    assert context_click_selection_action(already_selected=True, ctrl_held=False) == "keep"
    assert context_click_selection_action(already_selected=False, ctrl_held=True) == "additive"
    assert context_click_selection_action(already_selected=True, ctrl_held=True) == "additive"


if __name__ == "__main__":
    test_key_requests_trash()
    test_context_click_selection_action()
    print("file interaction checks passed")
