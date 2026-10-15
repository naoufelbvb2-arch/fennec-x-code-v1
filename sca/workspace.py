"""Local path boundaries, bounded UTF-8 snapshots and in-memory sessions.

This is a trusted-project boundary, not an OS sandbox against hostile processes.
All symlinks, junctions/reparse points and hardlinked files are refused.
"""

from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path, PureWindowsPath
import stat

from sca.contracts import AgentTask, ToolResult


class WorkspaceError(ValueError):
    """A workspace boundary, file type or concurrent-change check failed."""


PROTECTED_NAMES = frozenset({
    ".git", ".hg", ".svn", ".ssh", ".aws", ".azure", ".gnupg", ".config",
    ".codex", ".agents", ".netrc", ".npmrc", ".pypirc", ".gitconfig", ".git-credentials", ".docker",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
})
IGNORED_DIRECTORIES = frozenset({
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".cache",
    "build", "dist",
})


def prohibited_name(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered in PROTECTED_NAMES
        or lowered in IGNORED_DIRECTORIES
        or lowered.startswith((".env", "secret", "credentials"))
        or lowered.endswith((".pem", ".key", ".p12", ".pfx", ".egg-info"))
        or lowered in {"sca-v0-core-architecture-v0.1.md", "sca-v0-codex-i1-task.md"}
    )


def _is_link(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    )


def _identity(metadata: os.stat_result) -> tuple[int, ...]:
    # On Windows, fstat and path stat can report different ctime semantics.
    # Compare the portable identity/size/mtime/mode fields; patches also compare
    # SHA-256 against both the initial bytes and the immediate pre-write bytes.
    return (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns, metadata.st_mode)


@dataclass(frozen=True)
class TextSnapshot:
    path: str
    content: str
    sha256: str
    identity: tuple[int, ...]
    mode: int


@dataclass
class SessionContext:
    """One task's observed evidence; never inferred from model text."""

    workspace_root: Path
    task: AgentTask | None = None
    initial_git_status: str | None = None
    tool_results: list[ToolResult] = field(default_factory=list)


class Workspace:
    def __init__(self, root: str | Path, *, max_file_bytes: int = 1024 * 1024) -> None:
        if not isinstance(root, (str, Path)) or not str(root).strip():
            raise WorkspaceError("workspace root must be a non-empty path")
        if type(max_file_bytes) is not int or max_file_bytes < 1:
            raise ValueError("max_file_bytes must be a positive integer")
        candidate = Path(os.path.abspath(root))
        for ancestor in (candidate, *candidate.parents):
            if prohibited_name(ancestor.name):
                raise WorkspaceError("workspace root must not be inside a protected path")
            try:
                metadata = ancestor.lstat()
            except FileNotFoundError:
                raise WorkspaceError("workspace root must be an existing directory") from None
            if _is_link(metadata):
                raise WorkspaceError("workspace root and its parents must not be links or reparse points")
        if not candidate.is_dir():
            raise WorkspaceError("workspace root must be an existing directory")
        self.root = candidate.resolve(strict=True)
        if any(prohibited_name(part) for part in self.root.parts):
            raise WorkspaceError("workspace root resolves inside a protected path")
        self.max_file_bytes = max_file_bytes
        self._root_identity = self.root.stat().st_dev, self.root.stat().st_ino

    def _validate_root(self) -> None:
        metadata = self.root.lstat()
        if _is_link(metadata) or (metadata.st_dev, metadata.st_ino) != self._root_identity:
            raise WorkspaceError("workspace root changed after initialization")
        for ancestor in self.root.parents:
            if _is_link(ancestor.lstat()):
                raise WorkspaceError("workspace ancestor became a link")

    def resolve(self, relative: str, *, must_exist: bool = True) -> Path:
        """Accept portable relative paths only; refuse traversal and aliases."""
        self._validate_root()
        if not isinstance(relative, str) or not relative or "\\" in relative:
            raise WorkspaceError("path must be a non-empty relative path using / separators")
        if any(ord(char) < 32 for char in relative) or ":" in relative:
            raise WorkspaceError("control characters, drive paths and alternate data streams are prohibited")
        if Path(relative).is_absolute() or PureWindowsPath(relative).is_absolute():
            raise WorkspaceError("absolute paths are prohibited")
        parts = relative.split("/") if relative != "." else []
        current = self.root
        for part in parts:
            if not part or part in (".", "..") or part.rstrip(" .") != part:
                raise WorkspaceError("ambiguous path components or traversal are prohibited")
            stem = part.split(".")[0].casefold()
            if stem in {"con", "prn", "aux", "nul", *(f"com{i}" for i in "123456789¹²³"), *(f"lpt{i}" for i in "123456789¹²³")}:
                raise WorkspaceError("reserved device paths are prohibited")
            if prohibited_name(part):
                raise WorkspaceError(f"protected path: {part}")
            current = current / part
            try:
                metadata = current.lstat()
            except FileNotFoundError:
                continue
            if _is_link(metadata):
                raise WorkspaceError("symlinks, junctions and reparse points are prohibited")
            if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink != 1:
                raise WorkspaceError("hardlinked files are prohibited")
            if not (stat.S_ISREG(metadata.st_mode) or stat.S_ISDIR(metadata.st_mode)):
                raise WorkspaceError("special files are prohibited")
        resolved = current.resolve(strict=must_exist)
        if not resolved.is_relative_to(self.root):
            raise WorkspaceError("path escapes workspace")
        if any(prohibited_name(part) for part in resolved.relative_to(self.root).parts):
            raise WorkspaceError("resolved path aliases a protected path")
        return resolved

    def start_session(self, task: AgentTask) -> SessionContext:
        self._validate_root()
        if Path(os.path.abspath(task.workspace_root)) != self.root:
            raise WorkspaceError("task workspace does not match executor workspace")
        return SessionContext(workspace_root=self.root, task=task)

    def read_text(self, relative: str) -> TextSnapshot:
        path = self.resolve(relative)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise WorkspaceError("only regular, non-hardlinked text files may be read")
            raw = stream.read(self.max_file_bytes + 1)
            after = os.fstat(stream.fileno())
        if len(raw) > self.max_file_bytes:
            raise WorkspaceError("file exceeds maximum readable size")
        current = self.resolve(relative).stat()
        if _identity(before) != _identity(after) or _identity(after) != _identity(current):
            raise WorkspaceError("file changed while reading")
        if b"\0" in raw:
            raise WorkspaceError("binary files are not supported")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError("only UTF-8 text files are supported") from None
        return TextSnapshot(relative, content, hashlib.sha256(raw).hexdigest(), _identity(current), current.st_mode)

    def list_files(self, relative: str = ".", *, max_results: int = 200, max_entries: int = 10000) -> tuple[tuple[str, ...], bool]:
        if type(max_results) is not int or not 1 <= max_results <= 10000:
            raise WorkspaceError("max_results must be between 1 and 10000")
        if type(max_entries) is not int or not 1 <= max_entries <= 1000000:
            raise WorkspaceError("max_entries must be between 1 and 1000000")
        directory = self.resolve(relative)
        if not directory.is_dir():
            raise WorkspaceError("listing path must be a directory")
        pending = [directory]
        files: list[str] = []
        visited = 0
        while pending:
            directory = pending.pop()
            self.resolve(directory.relative_to(self.root).as_posix())
            entries = []
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    visited += 1
                    if visited > max_entries:
                        return tuple(sorted(files)), True
                    entries.append(entry)
            directories = []
            for entry in sorted(entries, key=lambda item: item.name):
                child = directory / entry.name
                child_relative = child.relative_to(self.root).as_posix()
                try:
                    safe_child = self.resolve(child_relative)
                except WorkspaceError:
                    continue
                if safe_child.is_dir():
                    directories.append(safe_child)
                else:
                    files.append(child_relative)
                    if len(files) >= max_results:
                        return tuple(sorted(files)), True
            pending.extend(reversed(directories))
        return tuple(sorted(files)), False
