from pathlib import Path

from trustworthy_assistant.config import AppConfig


class BootstrapLoader:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.workspace_dir = config.workspace_dir

    def load_file(self, name: str) -> str:
        path = self.workspace_dir / name
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def truncate_file(self, content: str, max_chars: int | None = None) -> str:
        limit = max_chars or self.config.max_file_chars
        if len(content) <= limit:
            return content
        cut = content.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        return content[:cut] + f"\n\n[... truncated ({len(content)} chars total, showing first {cut}) ...]"

    def load_all(self, mode: str = "full") -> dict[str, str]:
        if mode == "none":
            return {}
        names = ["AGENTS.md", "TOOLS.md"] if mode == "minimal" else list(self.config.bootstrap_files)
        result: dict[str, str] = {}
        total = 0
        for name in names:
            raw = self.load_file(name)
            if not raw:
                continue
            truncated = self.truncate_file(raw)
            if total + len(truncated) > self.config.max_total_chars:
                remaining = self.config.max_total_chars - total
                if remaining <= 0:
                    break
                truncated = self.truncate_file(raw, remaining)
            result[name] = truncated
            total += len(truncated)
        return result


def load_soul(workspace_dir: Path) -> str:
    path = workspace_dir / "SOUL.md"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
