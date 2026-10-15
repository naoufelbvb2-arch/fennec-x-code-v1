import hashlib
import stat
import subprocess

import pytest

from sca.contracts import ToolCall
from sca.tools import ToolRuntime


def patch_arguments(path="sample.txt", before="hello\n", after="updated\n"):
    return {
        "path": path,
        "expected_sha256": hashlib.sha256(before.encode("utf-8")).hexdigest(),
        "edits": [{"old": before, "new": after}],
    }


def test_file_listing_filters_sensitive_files_and_links(runtime, invoke):
    root = runtime.workspace.root
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('hello')", encoding="utf-8")
    (root / "README.md").write_text("hello", encoding="utf-8")
    (root / ".env").write_text("secret", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("secret", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "app.pyc").write_bytes(b"cache")

    result = invoke(runtime, "list_files")

    assert result.status == "SUCCESS"
    assert result.output.splitlines() == ["README.md", "src/app.py"]
    limited = invoke(runtime, "list_files", {"max_results": 1})
    assert len(limited.output.splitlines()) == 1
    assert limited.truncated


def test_read_file_line_range_and_hash(runtime, invoke):
    raw = b"one\r\ntwo\r\nthree\r\n"
    (runtime.workspace.root / "sample.txt").write_bytes(raw)
    result = invoke(runtime, "read_file", {"path": "sample.txt", "start_line": 2, "end_line": 2})
    assert result.status == "SUCCESS"
    assert f"sha256: {hashlib.sha256(raw).hexdigest()}" in result.output
    assert result.output.endswith("two\r\n")
    assert "three" not in result.output


@pytest.mark.parametrize("arguments", [
    {"start_line": 0}, {"start_line": 2, "end_line": 1}, {"start_line": True}, {"start_line": 9},
])
def test_invalid_read_ranges_rejected(runtime, invoke, arguments):
    (runtime.workspace.root / "sample.txt").write_text("hello\n", encoding="utf-8")
    assert invoke(runtime, "read_file", {"path": "sample.txt", **arguments}).status == "ERROR"


def test_search_literal_text_skips_sensitive_binary_and_oversized_files(runtime, invoke):
    root = runtime.workspace.root
    (root / "a.txt").write_text("needle\nother\nneedle [x]\n", encoding="utf-8")
    (root / ".env").write_text("needle secret", encoding="utf-8")
    (root / "binary").write_bytes(b"needle\0binary")
    (root / "large").write_bytes(b"needle" * 200000)
    result = invoke(runtime, "search_text", {"text": "needle"})
    assert result.status == "SUCCESS"
    assert result.output.splitlines() == ["a.txt:1:needle", "a.txt:3:needle [x]"]
    literal = invoke(runtime, "search_text", {"text": "[x]", "path": "a.txt"})
    assert literal.output == "a.txt:3:needle [x]"
    limited = invoke(runtime, "search_text", {"text": "needle", "max_results": 1})
    assert limited.truncated


@pytest.mark.parametrize("name, arguments", [
    ("list_files", {"path": "../outside"}),
    ("read_file", {"path": ".env"}),
    ("search_text", {"text": "value", "path": ".git"}),
    ("search_text", {"text": ""}),
    ("search_text", {"text": "a\nb"}),
    ("unknown", {}),
    ("list_files", {"extra": True}),
])
def test_invalid_or_protected_calls_return_correlated_errors(runtime, invoke, name, arguments):
    result = invoke(runtime, name, arguments, call_id="blocked")
    assert result.call_id == "blocked"
    assert result.status == "ERROR"
    assert result.error
    assert runtime.session.tool_results[-1] == result


def test_tool_output_is_capped_in_utf8_bytes(workspace, invoke):
    runtime = ToolRuntime(workspace, max_output_bytes=128)
    (workspace.root / "sample.txt").write_text("é" * 500, encoding="utf-8")
    result = invoke(runtime, "read_file", {"path": "sample.txt"})
    assert result.status == "SUCCESS"
    assert result.truncated
    assert len(result.output.encode("utf-8")) <= 128


@pytest.mark.parametrize("grant", [None, lambda call: False, lambda call: 1])
def test_write_permission_denial_preserves_file(workspace, invoke, grant):
    original = b"hello\n"
    target = workspace.root / "sample.txt"
    target.write_bytes(original)
    runtime = ToolRuntime(workspace, authorize=grant)
    result = invoke(runtime, "apply_patch", patch_arguments())
    assert result.status == "ERROR"
    assert "authorization denied" in result.error
    assert target.read_bytes() == original
    assert result.changed_files == ()


def test_valid_patch_is_atomic_and_preserves_unrelated_user_content(workspace, invoke):
    before = "user's existing change\r\nhello\r\n"
    target = workspace.root / "sample.txt"
    target.write_bytes(before.encode("utf-8"))
    runtime = ToolRuntime(workspace, authorize=lambda call: call.tool_name == "apply_patch")
    arguments = patch_arguments(before=before)
    arguments["edits"] = [{"old": "hello", "new": "updated"}]
    result = invoke(runtime, "apply_patch", arguments)
    assert result.status == "SUCCESS"
    assert result.changed_files == ("sample.txt",)
    assert target.read_bytes() == before.replace("hello", "updated").encode("utf-8")
    assert not list(workspace.root.glob(".fennec-*.tmp"))
    assert runtime.session.initial_git_status == "Not a Git repository at the workspace root."


@pytest.mark.parametrize("edits", [
    [], [{"old": "", "new": "x"}], [{"old": "absent", "new": "x"}],
    [{"old": "hello", "new": "hello"}], [{"old": "hello", "new": 1}],
    [{"old": "hello", "new": "x", "extra": True}],
    [{"old": "hello", "new": "x"}, {"old": "ell", "new": "y"}],
])
def test_invalid_patches_leave_file_unchanged(workspace, invoke, edits):
    target = workspace.root / "sample.txt"
    target.write_bytes(b"hello\n")
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    arguments = patch_arguments()
    arguments["edits"] = edits
    result = invoke(runtime, "apply_patch", arguments)
    assert result.status == "ERROR"
    assert target.read_bytes() == b"hello\n"
    assert not list(workspace.root.glob(".fennec-*.tmp"))


def test_ambiguous_patch_rejected(workspace, invoke):
    target = workspace.root / "sample.txt"
    target.write_text("hello hello", encoding="utf-8")
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    arguments = patch_arguments(before="hello hello")
    arguments["edits"] = [{"old": "hello", "new": "updated"}]
    assert invoke(runtime, "apply_patch", arguments).status == "ERROR"
    assert target.read_text(encoding="utf-8") == "hello hello"


def test_multiple_disjoint_edits_match_original_content(workspace, invoke):
    (workspace.root / "sample.txt").write_text("alpha beta", encoding="utf-8")
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    arguments = patch_arguments(before="alpha beta")
    arguments["edits"] = [{"old": "alpha", "new": "beta"}, {"old": "beta", "new": "gamma"}]
    result = invoke(runtime, "apply_patch", arguments)
    assert result.status == "SUCCESS"
    assert (workspace.root / "sample.txt").read_text(encoding="utf-8") == "beta gamma"


def test_stale_hash_and_invalid_hash_rejected(workspace, invoke):
    target = workspace.root / "sample.txt"
    target.write_text("user edited this", encoding="utf-8")
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    assert invoke(runtime, "apply_patch", patch_arguments()).status == "ERROR"
    invalid = patch_arguments()
    invalid["expected_sha256"] = "invalid"
    assert invoke(runtime, "apply_patch", invalid).status == "ERROR"
    assert target.read_text(encoding="utf-8") == "user edited this"


def test_concurrent_change_during_patch_preparation_is_preserved(workspace, invoke, monkeypatch):
    target = workspace.root / "sample.txt"
    target.write_bytes(b"hello\n")
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    original_read = workspace.read_text
    reads = 0

    def change_before_recheck(path):
        nonlocal reads
        reads += 1
        if reads == 2:
            target.write_bytes(b"new user change\n")
        return original_read(path)

    monkeypatch.setattr(workspace, "read_text", change_before_recheck)
    result = invoke(runtime, "apply_patch", patch_arguments())
    assert result.status == "ERROR"
    assert "file changed" in result.error
    assert target.read_bytes() == b"new user change\n"
    assert not list(workspace.root.glob(".fennec-*.tmp"))


@pytest.mark.parametrize("path", ["../outside.txt", ".git/config", ".env", "SCA-V0-Core-Architecture-v0.1.md"])
def test_protected_patch_paths_rejected(workspace, invoke, path):
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    result = invoke(runtime, "apply_patch", patch_arguments(path=path))
    assert result.status == "ERROR"
    assert result.changed_files == ()


def test_symlink_patch_escape_cannot_modify_target(workspace, tmp_path, directory_link, invoke):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "sample.txt"
    target.write_bytes(b"hello\n")
    directory_link(workspace.root / "escape", outside)
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    result = invoke(runtime, "apply_patch", patch_arguments(path="escape/sample.txt"))
    assert result.status == "ERROR"
    assert target.read_bytes() == b"hello\n"


def test_same_id_does_not_repeat_write(workspace, invoke):
    target = workspace.root / "sample.txt"
    target.write_bytes(b"hello\n")
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    assert invoke(runtime, "apply_patch", patch_arguments(), call_id="once").status == "SUCCESS"
    second = invoke(runtime, "apply_patch", patch_arguments(before="updated\n", after="again\n"), call_id="once")
    assert second.status == "ERROR"
    assert target.read_bytes() == b"updated\n"
    assert len(runtime.session.tool_results) == 1


def test_policy_exception_fails_closed(workspace, invoke):
    def broken_policy(call):
        raise RuntimeError("policy unavailable")

    runtime = ToolRuntime(workspace, authorize=broken_policy, trusted_project=True)
    result = invoke(runtime, "run_command", {"argv": ["python", "--version"]})
    assert result.status == "ERROR"
    assert "policy unavailable" in result.error


def initialize_git_fixture(root):
    base = ["git", "-c", f"safe.directory={root.as_posix()}", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid"]
    subprocess.run([*base, "init", "-q", str(root)], check=True, capture_output=True)
    (root / "sample.txt").write_bytes(b"hello\n")
    subprocess.run([*base, "-C", str(root), "add", "sample.txt"], check=True, capture_output=True)
    subprocess.run([*base, "-C", str(root), "commit", "-qm", "fixture"], check=True, capture_output=True)


def test_initial_git_status_captures_and_preserves_existing_user_changes(workspace, invoke):
    root = workspace.root
    initialize_git_fixture(root)
    before = "user change\nhello\n"
    (root / "sample.txt").write_bytes(before.encode("utf-8"))
    (root / "user-notes.txt").write_bytes(b"keep this\n")
    runtime = ToolRuntime(workspace, authorize=lambda call: True, trusted_project=True)
    arguments = patch_arguments(before=before)
    arguments["edits"] = [{"old": "hello", "new": "updated"}]

    result = invoke(runtime, "apply_patch", arguments)

    assert result.status == "SUCCESS", result.error
    assert " M sample.txt" in runtime.session.initial_git_status
    assert "?? user-notes.txt" in runtime.session.initial_git_status
    assert (root / "sample.txt").read_bytes() == b"user change\nupdated\n"
    assert (root / "user-notes.txt").read_bytes() == b"keep this\n"
    assert len(runtime.session.tool_results) == 1


def test_git_preflight_requires_its_own_explicit_authorization(workspace, invoke):
    initialize_git_fixture(workspace.root)
    runtime = ToolRuntime(workspace, authorize=lambda call: call.tool_name == "apply_patch", trusted_project=True)
    result = invoke(runtime, "apply_patch", patch_arguments())
    assert result.status == "ERROR"
    assert "authorization denied for run_command" in result.error
    assert (workspace.root / "sample.txt").read_bytes() == b"hello\n"


def test_read_only_patch_is_rejected_without_temporary_artifacts(workspace, invoke):
    target = workspace.root / "sample.txt"
    target.write_bytes(b"hello\n")
    target.chmod(stat.S_IRUSR)
    try:
        runtime = ToolRuntime(workspace, authorize=lambda call: True)
        result = invoke(runtime, "apply_patch", patch_arguments())
        assert result.status == "ERROR"
        assert "read-only" in result.error
        assert target.read_bytes() == b"hello\n"
        assert not list(workspace.root.glob(".fennec-*.tmp"))
    finally:
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_overlapping_occurrences_are_an_ambiguous_patch(workspace, invoke):
    target = workspace.root / "sample.txt"
    target.write_bytes(b"aaa")
    arguments = patch_arguments(before="aaa")
    arguments["edits"] = [{"old": "aa", "new": "z"}]
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    result = invoke(runtime, "apply_patch", arguments)
    assert result.status == "ERROR"
    assert "ambiguous" in result.error
    assert target.read_bytes() == b"aaa"


def test_no_net_change_patch_is_rejected(workspace, invoke):
    target = workspace.root / "sample.txt"
    target.write_bytes(b"ab")
    arguments = patch_arguments(before="ab")
    arguments["edits"] = [{"old": "a", "new": "ab"}, {"old": "b", "new": ""}]
    runtime = ToolRuntime(workspace, authorize=lambda call: True)
    result = invoke(runtime, "apply_patch", arguments)
    assert result.status == "ERROR"
    assert "no net content change" in result.error
    assert target.read_bytes() == b"ab"
