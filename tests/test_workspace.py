import hashlib
import os

import pytest

from sca.contracts import AgentTask
from sca.workspace import Workspace, WorkspaceError


def test_workspace_initialization_and_session(workspace):
    task = AgentTask("Inspect", str(workspace.root), "session-1")
    session = workspace.start_session(task)
    assert session.task == task
    assert session.workspace_root == workspace.root
    assert session.tool_results == []
    assert session.initial_git_status is None
    assert workspace.resolve(".") == workspace.root


def test_invalid_roots_rejected(tmp_path):
    with pytest.raises(WorkspaceError, match="existing directory"):
        Workspace(tmp_path / "missing")
    file = tmp_path / "file.txt"
    file.write_text("text", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="existing directory"):
        Workspace(file)
    protected = tmp_path / ".git"
    protected.mkdir()
    with pytest.raises(WorkspaceError, match="protected"):
        Workspace(protected)


def test_mismatched_session_workspace_rejected(workspace, tmp_path):
    with pytest.raises(WorkspaceError, match="does not match"):
        workspace.start_session(AgentTask("Task", str(tmp_path), "session"))


def test_valid_file_access_retains_newlines_and_hash(workspace):
    raw = "first\r\nsecond café\r\n".encode("utf-8")
    (workspace.root / "sample.txt").write_bytes(raw)
    snapshot = workspace.read_text("sample.txt")
    assert snapshot.content.encode("utf-8") == raw
    assert snapshot.sha256 == hashlib.sha256(raw).hexdigest()
    assert snapshot.path == "sample.txt"


@pytest.mark.parametrize("path", [
    "../outside.txt", "src/../../outside.txt", "/etc/passwd", "C:/outside.txt",
    "C:outside.txt", "//server/share/file", "\\\\server\\share\\file", "src\\file.txt",
    "file.txt:stream", "src/./file.txt", "src//file.txt", "file.txt ", "file.txt.",
    "NUL", "con.txt", "COM1.py", "LPT9", "COM¹.txt", "bad\0path", "bad\npath",
])
def test_path_traversal_and_platform_aliases_rejected(workspace, path):
    with pytest.raises(WorkspaceError):
        workspace.resolve(path, must_exist=False)


@pytest.mark.parametrize("path", [
    ".git/config", ".Git/HEAD", ".env", ".env.local", ".ssh/id_rsa",
    ".aws/credentials", "credentials.json", "secrets.toml", "private.key", "cert.pem",
    "src/.env.production", ".npmrc", ".netrc", "SCA-V0-Core-Architecture-v0.1.md",
])
def test_sensitive_paths_rejected_before_access(workspace, path):
    with pytest.raises(WorkspaceError, match="protected"):
        workspace.resolve(path, must_exist=False)


def test_directory_symlink_escape_rejected(workspace, tmp_path, directory_link):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside-data", encoding="utf-8")
    link = workspace.root / "escape"
    directory_link(link, outside)
    with pytest.raises(WorkspaceError, match="reparse|symlink"):
        workspace.read_text("escape/secret.txt")
    files, _ = workspace.list_files()
    assert "escape/secret.txt" not in files


def test_linked_workspace_root_and_in_root_links_rejected(tmp_path, directory_link):
    root = tmp_path / "real"
    root.mkdir()
    linked_root = tmp_path / "linked"
    directory_link(linked_root, root)
    with pytest.raises(WorkspaceError, match="links|reparse"):
        Workspace(linked_root)
    (root / "source").mkdir()
    workspace = Workspace(root)
    directory_link(root / "alias", root / "source")
    with pytest.raises(WorkspaceError, match="reparse|symlink"):
        workspace.resolve("alias")


def test_hardlinked_files_rejected(workspace, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    os.link(outside, workspace.root / "alias.txt")
    with pytest.raises(WorkspaceError, match="hardlinked"):
        workspace.read_text("alias.txt")


@pytest.mark.parametrize("raw", [b"binary\0data", b"\xff\xfeinvalid"])
def test_non_utf8_or_binary_files_rejected(workspace, raw):
    (workspace.root / "data").write_bytes(raw)
    with pytest.raises(WorkspaceError):
        workspace.read_text("data")


def test_file_size_limit(workspace):
    (workspace.root / "large").write_bytes(b"x" * 9)
    restricted = Workspace(workspace.root, max_file_bytes=8)
    with pytest.raises(WorkspaceError, match="maximum readable size"):
        restricted.read_text("large")


def test_root_replacement_rejected(workspace):
    previous = workspace.root.with_name("previous")
    workspace.root.rename(previous)
    workspace.root.mkdir()
    with pytest.raises(WorkspaceError, match="root changed"):
        workspace.resolve(".")


def test_listing_scan_limit_is_bounded(workspace):
    for number in range(5):
        (workspace.root / f"{number}.txt").write_text("text", encoding="utf-8")
    _, truncated = workspace.list_files(max_entries=3)
    assert truncated
