import re

from trustworthy_assistant.memory.models import MemoryRecord


MANAGED_MEMORY_START = "<!-- ledger-memory:start -->"
MANAGED_MEMORY_END = "<!-- ledger-memory:end -->"


class MemoryProjector:
    def __init__(self) -> None:
        self.groups = [
            ("preference", "## Preferences"),
            ("project", "## Active Project"),
            ("decision", "## Decisions"),
            ("constraint", "## Constraints"),
            ("profile", "## Profile"),
            ("fact", "## Facts"),
            ("context", "## Context"),
            ("general", "## General"),
        ]

    @staticmethod
    def display_value(record: MemoryRecord) -> str:
        if record.value and record.value not in {"zh-CN", "en-US", "concise"}:
            return record.value
        return record.summary

    @staticmethod
    def sort_key(record: MemoryRecord) -> tuple[float, str, str]:
        return (record.importance, record.last_seen_at, record.memory_id)

    def build_block(self, records: list[MemoryRecord]) -> str:
        grouped = {kind: [] for kind, _ in self.groups}
        for record in sorted(records, key=self.sort_key, reverse=True):
            grouped.setdefault(record.kind, []).append(record)

        lines = [
            MANAGED_MEMORY_START,
            "## Ledger Memory View",
            "",
            "> This section is managed automatically from the structured memory ledger.",
            "> Edit the ledger via the assistant workflow instead of changing this block by hand.",
            "",
        ]
        emitted = False
        for kind, title in self.groups:
            rows = grouped.get(kind, [])
            if not rows:
                continue
            emitted = True
            lines.append(title)
            lines.append("")
            for record in rows:
                lines.append(f"- {self.display_value(record)} [{record.slot}]")
            lines.append("")
        if not emitted:
            lines.extend(["## Ledger Memory View", "", "- (no confirmed memory yet)", ""])
        lines.append(MANAGED_MEMORY_END)
        return "\n".join(lines).strip() + "\n"

    def sync(self, existing: str, confirmed_records: list[MemoryRecord]) -> str:
        block = self.build_block(confirmed_records)
        if MANAGED_MEMORY_START in existing and MANAGED_MEMORY_END in existing:
            pattern = re.compile(
                rf"{re.escape(MANAGED_MEMORY_START)}[\s\S]*?{re.escape(MANAGED_MEMORY_END)}\n?",
                re.MULTILINE,
            )
            return pattern.sub(block, existing, count=1)
        base = existing.rstrip()
        return f"{base}\n\n{block}" if base else block
