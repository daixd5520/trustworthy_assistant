from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from trustworthy_assistant.memory.service import TrustworthyMemoryService

_HOME = Path.home()
_BLOCKED_PREFIXES = [
    Path("/etc"), Path("/var"), Path("/sys"), Path("/proc"), Path("/dev"),
    Path("/sbin"), Path("/usr/sbin"),
    _HOME / ".ssh",
    _HOME / ".gnupg",
    _HOME / ".aws",
    _HOME / ".kube",
]


def _local_now_str() -> str:
    now = datetime.now().astimezone()
    offset = now.strftime("%z")
    offset_fmt = f"UTC{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
    return now.strftime(f"%Y-%m-%d %H:%M {offset_fmt}")


def _resolve_safe_path(path: str, workspace_dir: Path) -> Path:
    raw = path.strip()
    if raw.startswith("~"):
        candidate = Path(raw).expanduser().resolve()
    elif raw.startswith("/"):
        candidate = Path(raw).resolve()
    else:
        candidate = (workspace_dir / raw).resolve()
    for blocked in _BLOCKED_PREFIXES:
        try:
            candidate.relative_to(blocked)
            raise ValueError(f"Access denied: {path} is inside a protected directory")
        except ValueError:
            if candidate == blocked or blocked in candidate.parents:
                raise ValueError(f"Access denied: {path} is inside a protected directory")
    if not candidate.exists():
        return candidate
    try:
        candidate.resolve().relative_to(_HOME)
    except ValueError:
        if candidate != _HOME and _HOME not in candidate.parents:
            raise ValueError(f"Access denied: {path} is outside home directory")
    return candidate


class ToolRegistry:
    def __init__(self, memory_service: TrustworthyMemoryService, on_tool: Callable[[str, str], None] | None = None, reminder_callback: Callable[[str, int, str, str], None] | None = None, file_sender: Callable[[str, str, str], None] | None = None) -> None:
        self.memory_service = memory_service
        self.on_tool = on_tool
        self.reminder_callback = reminder_callback
        self.file_sender = file_sender
        self.workspace_dir = self.memory_service.repository.paths.workspace_dir
        self._current_channel: str = "terminal"
        self._current_user_id: str = "local"
        self.tools = [
            {
                "name": "memory_write",
                "description": "Save an important fact or observation to long-term memory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "The fact or observation to remember."},
                        "category": {"type": "string", "description": "Category: preference, fact, context, etc."},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "memory_search",
                "description": "Search stored memories for relevant information, ranked by similarity.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query."},
                        "top_k": {"type": "integer", "description": "Max results. Default: 5."},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "list_directory",
                "description": "List files and directories. Supports workspace-relative paths, absolute paths, and ~/ paths. Access is limited to your home directory with system directories blocked.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to list. Can be relative (workspace), absolute (/Users/...), or home-relative (~/Downloads). Default: ."},
                    },
                },
            },
            {
                "name": "read_file",
                "description": "Read a text file. Supports workspace-relative paths, absolute paths, and ~/ paths. Access is limited to your home directory with system directories blocked.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path. Can be relative (workspace), absolute (/Users/...), or home-relative (~/Documents/notes.txt)."},
                        "max_chars": {"type": "integer", "description": "Max characters to return. Default: 4000."},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "get_current_time",
                "description": "Get the current local time with timezone.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "set_reminder",
                "description": "Set a one-off reminder that fires after a delay. The reminder message will be sent to you when it triggers.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "The reminder message to send when it triggers."},
                        "delay_minutes": {"type": "integer", "description": "Number of minutes from now to trigger the reminder."},
                    },
                    "required": ["message", "delay_minutes"],
                },
            },
            {
                "name": "send_file",
                "description": "Send a file from the local filesystem to the user via the current channel (e.g., WeChat). Supports images, videos, documents, and other files up to 20MB. Images and videos are sent in their native format for optimal display. Only works when connected through a channel that supports file delivery (like WeChat).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file to send. Can be relative (workspace), absolute (/Users/...), or home-relative (~/Documents/report.pdf)."},
                        "caption": {"type": "string", "description": "Optional text caption to include with the file."},
                    },
                    "required": ["path"],
                },
            },
        ]
        self.handlers: dict[str, Callable[..., str]] = {
            "memory_write": self.memory_write,
            "memory_search": self.memory_search,
            "list_directory": self.list_directory,
            "read_file": self.read_file,
            "get_current_time": self.get_current_time,
            "set_reminder": self.set_reminder,
            "send_file": self.send_file,
        }

    def set_channel_context(self, channel: str, user_id: str) -> None:
        self._current_channel = channel
        self._current_user_id = user_id

    def emit(self, name: str, detail: str) -> None:
        if self.on_tool:
            self.on_tool(name, detail)

    def memory_write(self, content: str, category: str = "general") -> str:
        self.emit("memory_write", f"[{category}] {content[:60]}...")
        return self.memory_service.write_memory(content, category)

    def memory_search(self, query: str, top_k: int = 5) -> str:
        self.emit("memory_search", query)
        results = self.memory_service.hybrid_search(query, top_k)
        if not results:
            return "No relevant memories found."
        return "\n".join(
            f"[{item['path']}] (score: {item['score']}, status: {item['status']}) {item['snippet']}"
            for item in results
        )

    def list_directory(self, path: str = ".") -> str:
        self.emit("list_directory", path)
        target = _resolve_safe_path(path, self.workspace_dir)
        if not target.exists():
            return f"Error: Path not found: {path}"
        if not target.is_dir():
            return f"Error: Not a directory: {path}"
        rows = []
        for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:200]:
            suffix = "/" if child.is_dir() else ""
            rows.append(child.name + suffix)
        return "\n".join(rows) if rows else "(empty)"

    def read_file(self, path: str, max_chars: int = 4000) -> str:
        self.emit("read_file", path)
        target = _resolve_safe_path(path, self.workspace_dir)
        if not target.exists():
            return f"Error: Path not found: {path}"
        if not target.is_file():
            return f"Error: Not a file: {path}"
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n\n[... truncated, total {len(text)} chars ...]"

    def get_current_time(self) -> str:
        self.emit("get_current_time", "local")
        return _local_now_str()

    def set_reminder(self, message: str, delay_minutes: int) -> str:
        self.emit("set_reminder", f"{delay_minutes}m: {message[:40]}")
        if self.reminder_callback is None:
            return "Error: Reminders are not available in this session."
        if delay_minutes < 1:
            return "Error: delay_minutes must be at least 1."
        if delay_minutes > 1440:
            return "Error: delay_minutes must be at most 1440 (24 hours)."
        try:
            self.reminder_callback(message, delay_minutes, self._current_channel, self._current_user_id)
            return f"Reminder set: will notify you in {delay_minutes} minute(s)."
        except Exception as exc:
            return f"Error: Failed to set reminder: {exc}"

    def send_file(self, path: str, caption: str = "") -> str:
        self.emit("send_file", path)
        if self.file_sender is None:
            return "Error: File sending is not available in this session. Only available when connected via WeChat."
        try:
            target = _resolve_safe_path(path, self.workspace_dir)
        except ValueError as exc:
            return f"Error: {exc}"
        if not target.exists():
            return f"Error: File not found: {path}"
        if not target.is_file():
            return f"Error: Not a file: {path}"
        file_size = target.stat().st_size
        if file_size > 20 * 1024 * 1024:
            return f"Error: File too large ({file_size} bytes). Maximum size is 20MB."
        if file_size == 0:
            return f"Error: File is empty: {path}"
        try:
            self.file_sender(str(target), self._current_channel, self._current_user_id)
            return f"File sent: {target.name} ({file_size} bytes)"
        except Exception as exc:
            return f"Error: Failed to send file: {exc}"

    def format_prompt_block(self) -> str:
        lines = [
            "## Registered Tools",
            "",
            "Only call tools that appear in this section. Do not invent tool names.",
            "",
        ]
        for tool in self.tools:
            lines.append(f"- `{tool['name']}`: {tool['description']}")
        return "\n".join(lines)

    def process_tool_call(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        handler = self.handlers.get(tool_name)
        if handler is None:
            return f"Error: Unknown tool '{tool_name}'"
        try:
            return handler(**tool_input)
        except TypeError as exc:
            return f"Error: Invalid arguments for {tool_name}: {exc}"
        except Exception as exc:
            return f"Error: {tool_name} failed: {exc}"
