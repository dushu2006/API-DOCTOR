"""Tests for unified-diff validation and application."""

from __future__ import annotations

import difflib

import pytest

from app.sandbox.patch_utils import (
    PatchError,
    apply_patch,
    apply_patch_idempotent,
    validate_diff,
)

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


def test_apply_patch_relocates_wrong_line_numbers(tmp_path):
    """LLM hunks often claim the wrong @@ line; apply by matching context."""
    target = tmp_path / "app" / "demo_api"
    target.mkdir(parents=True)
    (target / "bugs.py").write_text(
        "# header\n# more header\ndef foo():\n    return 1\n"
    )
    # Header says line 1, but `def foo` is actually line 3.
    off_by_n = (
        "--- a/app/demo_api/bugs.py\n"
        "+++ b/app/demo_api/bugs.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def foo():\n"
        "-    return 1\n"
        "+    return 2\n"
    )
    affected = apply_patch(off_by_n, tmp_path)
    assert affected == ["app/demo_api/bugs.py"]
    assert (target / "bugs.py").read_text() == "# header\n# more header\ndef foo():\n    return 2\n"


def test_apply_patch_tolerates_trailing_whitespace(tmp_path):
    target = tmp_path / "app" / "demo_api"
    target.mkdir(parents=True)
    (target / "bugs.py").write_text("def foo():\n    return 1   \n")
    affected = apply_patch(_diff(), tmp_path)
    assert affected == ["app/demo_api/bugs.py"]
    assert "return 2" in (target / "bugs.py").read_text()


def test_apply_patch_legacy_mock_hunk_at_line_121(tmp_path):
    """The previous MockAIClient hunk claimed line 121 for `def charge_user`.

    That is the exact 'context mismatch at line 121' failure from auto_trigger.
    The applicator must relocate the hunk to the real function.
    """
    source = (
        "# padding\n" * 116
        + "def charge_user(user_id: str, amount: float) -> str:\n"
        + "    user = get_user(user_id)\n"
        + "    if user is None:\n"
        + '        raise LookupError(f"user {user_id!r} not found")\n'
        + "    token = user.payment_method.token  # BUG: no null check on payment_method\n"
        + '    return f"txn_{token}_{amount:.2f}"\n'
    )
    target = tmp_path / "app" / "demo_api"
    target.mkdir(parents=True)
    (target / "bugs.py").write_text(source)
    legacy = (
        "--- a/app/demo_api/bugs.py\n"
        "+++ b/app/demo_api/bugs.py\n"
        "@@ -121,1 +121,5 @@\n"
        " def charge_user(user_id: str, amount: float) -> str:\n"
        "     user = get_user(user_id)\n"
        "     if user is None:\n"
        '         raise LookupError(f"user {user_id!r} not found")\n'
        "-    token = user.payment_method.token  # BUG: no null check on payment_method\n"
        "+    if user.payment_method is None:\n"
        "+        token = \"no_payment\"\n"
        "+    else:\n"
        "+        token = user.payment_method.token\n"
        '     return f"txn_{token}_{amount:.2f}"\n'
    )
    apply_patch(legacy, tmp_path)
    patched = (target / "bugs.py").read_text()
    assert "token = \"no_payment\"" in patched
    assert "payment_method is None" in patched


def test_apply_patch_is_transactional_across_files(tmp_path):
    """A mismatch in a later file must not leave an earlier file modified."""
    (tmp_path / "one.py").write_text("one = 1\n")
    (tmp_path / "two.py").write_text("two = 999\n")
    diff = (
        "--- a/one.py\n"
        "+++ b/one.py\n"
        "@@ -1 +1 @@\n"
        "-one = 1\n"
        "+one = 2\n"
        "--- a/two.py\n"
        "+++ b/two.py\n"
        "@@ -1 +1 @@\n"
        "-two = 1\n"
        "+two = 2\n"
    )

    with pytest.raises(PatchError, match="mismatch"):
        apply_patch(diff, tmp_path)

    assert (tmp_path / "one.py").read_text() == "one = 1\n"
    assert (tmp_path / "two.py").read_text() == "two = 999\n"


def test_idempotent_apply_recognizes_exact_postimage(tmp_path):
    target = tmp_path / "app" / "demo_api"
    target.mkdir(parents=True)
    path = target / "bugs.py"
    path.write_text(ORIGINAL)
    apply_patch(_diff(), tmp_path)

    affected, already_applied = apply_patch_idempotent(_diff(), tmp_path)

    assert affected == ["app/demo_api/bugs.py"]
    assert already_applied == ["app/demo_api/bugs.py"]
    assert path.read_text() == FIXED


def test_new_file_patch_never_overwrites_existing_content(tmp_path):
    (tmp_path / "new.py").write_text("user content\n")
    diff = (
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1 @@\n"
        "+generated content\n"
    )

    with pytest.raises(PatchError, match="already exists"):
        apply_patch(diff, tmp_path)

    assert (tmp_path / "new.py").read_text() == "user content\n"


def test_idempotent_new_file_patch_accepts_exact_postimage(tmp_path):
    (tmp_path / "new.py").write_text("generated content\n")
    diff = (
        "--- /dev/null\n"
        "+++ b/new.py\n"
        "@@ -0,0 +1 @@\n"
        "+generated content\n"
    )

    affected, already_applied = apply_patch_idempotent(diff, tmp_path)

    assert affected == ["new.py"]
    assert already_applied == ["new.py"]


def test_delete_patch_and_idempotent_retry(tmp_path):
    diff = (
        "--- a/obsolete.py\n"
        "+++ /dev/null\n"
        "@@ -1 +0,0 @@\n"
        "-obsolete = True\n"
    )
    path = tmp_path / "obsolete.py"
    path.write_text("obsolete = True\n")

    assert apply_patch(diff, tmp_path) == ["obsolete.py"]
    assert not path.exists()
    affected, already_applied = apply_patch_idempotent(diff, tmp_path)
    assert affected == ["obsolete.py"]
    assert already_applied == ["obsolete.py"]
    assert not path.exists()


def test_idempotent_apply_recovers_partially_applied_multifile_patch(tmp_path):
    (tmp_path / "one.py").write_text("one = 2\n")  # first file already applied
    (tmp_path / "two.py").write_text("two = 1\n")
    diff = (
        "--- a/one.py\n"
        "+++ b/one.py\n"
        "@@ -1 +1 @@\n"
        "-one = 1\n"
        "+one = 2\n"
        "--- a/two.py\n"
        "+++ b/two.py\n"
        "@@ -1 +1 @@\n"
        "-two = 1\n"
        "+two = 2\n"
    )

    affected, already_applied = apply_patch_idempotent(diff, tmp_path)

    assert affected == ["one.py", "two.py"]
    assert already_applied == ["one.py"]
    assert (tmp_path / "one.py").read_text() == "one = 2\n"
    assert (tmp_path / "two.py").read_text() == "two = 2\n"
