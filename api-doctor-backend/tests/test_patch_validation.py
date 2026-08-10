"""Tests for unified-diff validation and application."""

from __future__ import annotations

import difflib

import pytest

from app.sandbox.patch_utils import PatchError, apply_patch, validate_diff

ORIGINAL = "def foo():\n    return 1\n"
FIXED = "def foo():\n    return 2\n"


def _diff():
    diff = "\n".join(
        difflib.unified_diff(
            ORIGINAL.splitlines(), FIXED.splitlines(),
            fromfile="a/app/demo_api/bugs.py", tofile="b/app/demo_api/bugs.py", lineterm="",
        )
    )
    return diff + "\n"


def test_validate_diff_ok():
    affected = validate_diff(_diff())
    assert affected == ["app/demo_api/bugs.py"]


def test_validate_diff_rejects_empty():
    with pytest.raises(PatchError):
        validate_diff("")


def test_validate_diff_rejects_absolute_path():
    bad = "--- /etc/passwd\n+++ /etc/passwd\n@@ -1 +1 @@\n-x\n+y\n"
    with pytest.raises(PatchError):
        validate_diff(bad)


def test_validate_diff_rejects_path_traversal():
    bad = "--- a/../../secrets\n+++ b/../../secrets\n@@ -1 +1 @@\n-x\n+y\n"
    with pytest.raises(PatchError):
        validate_diff(bad)


def test_apply_patch(tmp_path):
    target = tmp_path / "app" / "demo_api"
    target.mkdir(parents=True)
    (target / "bugs.py").write_text(ORIGINAL)
    affected = apply_patch(_diff(), tmp_path)
    assert affected == ["app/demo_api/bugs.py"]
    assert (target / "bugs.py").read_text() == FIXED


def test_apply_patch_fails_on_mismatch(tmp_path):
    target = tmp_path / "app" / "demo_api"
    target.mkdir(parents=True)
    (target / "bugs.py").write_text("def foo():\n    return 999\n")  # context mismatch
    with pytest.raises(PatchError):
        apply_patch(_diff(), tmp_path)
