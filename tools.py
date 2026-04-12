from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from trustworthy_assistant.memory.service import TrustworthyMemoryService


class ToolRegistry:
    def __init__(self, memory_service: TrustworthyMemoryService, on_tool: Callable[[str, str], None] | None = None) -> None:
        self.memory_service = memory_service
        self.on_tool = on_tool
        self.workspace_dir = self.memory_service.repository.paths.workspace_dir
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
                "description": "List files and directories within the workspace.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path inside the workspace. Default: ."},
                    },
                },
            },
            {
                "name": "read_file",
                "description": "Read a text file within the workspace.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative file path inside the workspace."},
                        "max_chars": {"type": "integer", "description": "Max characters to return. Default: 4000."},
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "get_current_time",
                "description": "Get the current UTC time.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]
        self.handlers: dict[str, Callable[..., str]] = {
            "memory_write": self.memory_write,
            "memory_search": self.memory_search,
            "list_directory": self.list_directory,
            "read_file": self.read_file,
            "get_current_time": self.get_current_time,
        }

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

    def _resolve_workspace_path(self, path: str) -> Path:
        candidate = (self.workspace_dir / (path or ".")).resolve()
        workspace = self.workspace_dir.resolve()
        if candidate != workspace and workspace not in candidate.parents:
            raise ValueError("Path escapes workspace")
        return candidate

    def list_directory(self, path: str = ".") -> str:
        self.emit("list_directory", path)
        target = self._resolve_workspace_path(path)
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
        target = self._resolve_workspace_path(path)
        if not target.exists():
            return f"Error: Path not found: {path}"
        if not target.is_file():
            return f"Error: Not a file: {path}"
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + f"\n\n[... truncated, total {len(text)} chars ...]"

    def get_current_time(self) -> str:
        self.emit("get_current_time", "utc")
        return datetime.now(timezone.utc).isoformat()

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
