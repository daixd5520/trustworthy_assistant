import json
from dataclasses import dataclass
from pathlib import Path

from trustworthy_assistant.memory.models import EvidenceRecord, MemoryEvent, MemoryRecord, RetrievalTrace


@dataclass(frozen=True, slots=True)
class MemoryPaths:
    workspace_dir: Path
    memory_root: Path
    daily_dir: Path
    ledger_dir: Path
    review_dir: Path
    memories_file: Path
    events_file: Path
    evidence_file: Path
    traces_file: Path
    markdown_file: Path

    @classmethod
    def from_workspace(cls, workspace_dir: Path) -> "MemoryPaths":
        memory_root = workspace_dir / "memory"
        daily_dir = memory_root / "daily"
        ledger_dir = memory_root / "ledger"
        review_dir = memory_root / "review"
        return cls(
            workspace_dir=workspace_dir,
            memory_root=memory_root,
            daily_dir=daily_dir,
            ledger_dir=ledger_dir,
            review_dir=review_dir,
            memories_file=ledger_dir / "memories.jsonl",
            events_file=ledger_dir / "events.jsonl",
            evidence_file=ledger_dir / "evidence.jsonl",
            traces_file=ledger_dir / "traces.jsonl",
            markdown_file=workspace_dir / "MEMORY.md",
        )


class MemoryLedgerRepository:
    def __init__(self, workspace_dir: Path) -> None:
        self.paths = MemoryPaths.from_workspace(workspace_dir)
        self.paths.daily_dir.mkdir(parents=True, exist_ok=True)
        self.paths.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.paths.review_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def append_jsonl(path: Path, payload: dict) -> None:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def read_jsonl(path: Path) -> list[dict]:
        if not path.is_file():
            return []
        rows: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except Exception:
            return []
        return rows

    def append_memory(self, record: MemoryRecord) -> None:
        self.append_jsonl(self.paths.memories_file, record.to_dict())

    def append_event(self, event: MemoryEvent) -> None:
        self.append_jsonl(self.paths.events_file, event.to_dict())

    def append_evidence(self, evidence: EvidenceRecord) -> None:
        self.append_jsonl(self.paths.evidence_file, evidence.to_dict())

    def append_trace(self, trace: RetrievalTrace) -> None:
        self.append_jsonl(self.paths.traces_file, trace.to_dict())

    def append_daily_entry(self, payload: dict) -> None:
        day = payload["ts"][:10]
        self.append_jsonl(self.paths.daily_dir / f"{day}.jsonl", payload)

    def load_latest_memories(self) -> list[MemoryRecord]:
        latest: dict[str, MemoryRecord] = {}
        for row in self.read_jsonl(self.paths.memories_file):
            memory_id = row.get("memory_id")
            if not memory_id:
                continue
            latest[memory_id] = MemoryRecord.from_dict(row)
        return list(latest.values())

    def load_memory_map(self) -> dict[str, MemoryRecord]:
        return {record.memory_id: record for record in self.load_latest_memories()}

    def load_daily_entries(self) -> list[dict]:
        entries: list[dict] = []
        if not self.paths.daily_dir.is_dir():
            return entries
        for jsonl_file in sorted(self.paths.daily_dir.glob("*.jsonl")):
            for row in self.read_jsonl(jsonl_file):
                row["_path"] = jsonl_file.name
                entries.append(row)
        return entries

    def trace_count(self) -> int:
        return len(self.read_jsonl(self.paths.traces_file))

    def load_events(self, memory_id: str = "") -> list[dict]:
        rows = self.read_jsonl(self.paths.events_file)
        if memory_id:
            rows = [row for row in rows if row.get("memory_id") == memory_id]
        return rows

    def load_evidence(self) -> list[dict]:
        return self.read_jsonl(self.paths.evidence_file)

    def read_markdown(self) -> str:
        if not self.paths.markdown_file.is_file():
            return ""
        try:
            return self.paths.markdown_file.read_text(encoding="utf-8")
        except Exception:
            return ""

    def write_markdown(self, content: str) -> None:
        self.paths.markdown_file.write_text(content, encoding="utf-8")
