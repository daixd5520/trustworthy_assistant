from datetime import datetime, timezone
import uuid
import re
from typing import Any, Optional
from pathlib import Path

from trustworthy_assistant.memory.models import (
    EvidenceRecord,
    MemoryEvent,
    MemoryRecord,
    RetrievalTrace,
    RetrievalTraceItem,
)
from trustworthy_assistant.memory.projector import MemoryProjector
from trustworthy_assistant.memory.repository import MemoryLedgerRepository
from trustworthy_assistant.memory.retriever import MemoryRetriever
from trustworthy_assistant.memory.vector_store import VectorStore


class TrustworthyMemoryService:
    def __init__(self, workspace_dir, openai_api_key: Optional[str] = None, 
                 openai_base_url: Optional[str] = None, embedding_model: str = "text-embedding-3-small",
                 chroma_persist_dir: Optional[str] = None) -> None:
        self.repository = MemoryLedgerRepository(workspace_dir)
        self.projector = MemoryProjector()
        self.retriever = MemoryRetriever()
        self.last_trace: RetrievalTrace | None = None
        
        persist_path = Path(chroma_persist_dir) if chroma_persist_dir else workspace_dir / "chroma"
        self.vector_store = VectorStore(
            persist_dir=persist_path,
            openai_api_key=openai_api_key,
            openai_base_url=openai_base_url,
            embedding_model=embedding_model
        )

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in items:
            if not item or item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def normalize_category(category: str) -> str:
        value = (category or "general").strip().lower()
        return value or "general"

    def kind_for_category(self, category: str) -> str:
        value = self.normalize_category(category)
        if value in {"preference", "fact", "context", "project", "decision", "constraint", "profile"}:
            return value
        if value in {"language", "style"}:
            return "preference"
        return "general"

    def slot_for(self, category: str, content: str) -> str:
        value = self.normalize_category(category)
        lowered = content.lower()
        if value in {"language", "preference"}:
            if "中文" in content or "chinese" in lowered:
                return "language.primary"
            if "英文" in content or "english" in lowered:
                return "language.primary"
            if "简洁" in content or "concise" in lowered:
                return "response.style"
        if value == "project":
            return "project.current"
        if value == "decision":
            return "decision.current"
        if value == "constraint":
            return "constraint.current"
        if value == "profile":
            return "profile.general"
        if value == "fact":
            return "fact.general"
        if value == "context":
            return "context.general"
        return f"{self.kind_for_category(value)}.{value}"

    @staticmethod
    def summary_for(content: str, limit: int = 120) -> str:
        text = " ".join(content.strip().split())
        if len(text) <= limit:
            return text
        return text[:limit] + "..."

    def value_for(self, slot: str, content: str) -> str:
        lowered = content.lower()
        if slot == "language.primary":
            if "中文" in content or "chinese" in lowered:
                return "zh-CN"
            if "英文" in content or "english" in lowered:
                return "en-US"
        if slot == "response.style":
            if "简洁" in content or "concise" in lowered:
                return "concise"
        return content.strip()

    @staticmethod
    def fingerprint_for(kind: str, slot: str, value: str) -> str:
        return f"{kind}|{slot}|{value.strip().lower()}"

    def create_evidence(self, source_type: str, text_span: str, category: str, session_key: str = "") -> str:
        evidence = EvidenceRecord(
            evidence_id=self.new_id("ev"),
            source_type=source_type,
            category=self.normalize_category(category),
            session_key=session_key,
            text_span=text_span,
            timestamp=self.now_iso(),
        )
        self.repository.append_evidence(evidence)
        return evidence.evidence_id

    def append_event(self, action: str, memory_id: str, reason: str, from_status: str = "", to_status: str = "") -> None:
        self.repository.append_event(
            MemoryEvent(
                event_id=self.new_id("evt"),
                memory_id=memory_id,
                action=action,
                reason=reason,
                from_status=from_status,
                to_status=to_status,
                timestamp=self.now_iso(),
            )
        )

    def load_latest_memories(self) -> list[MemoryRecord]:
        return self.repository.load_latest_memories()

    def load_memory_map(self) -> dict[str, MemoryRecord]:
        return self.repository.load_memory_map()

    def find_conflicts(self, slot: str, value: str, current_id: str = "") -> list[str]:
        if slot not in {"language.primary", "response.style", "project.current", "decision.current", "constraint.current"}:
            return []
        conflicts: list[str] = []
        for record in self.load_latest_memories():
            if current_id and record.memory_id == current_id:
                continue
            if record.status not in {"candidate", "confirmed", "disputed"}:
                continue
            if record.slot != slot or record.value == value:
                continue
            conflicts.append(record.memory_id)
        return conflicts

    def managed_confirmed_records(self) -> list[MemoryRecord]:
        records = [record for record in self.load_latest_memories() if record.status == "confirmed"]
        records.sort(key=self.projector.sort_key, reverse=True)
        return records

    def sync_memory_markdown(self) -> str:
        existing = self.repository.read_markdown()
        updated = self.projector.sync(existing, self.managed_confirmed_records())
        if updated != existing:
            self.repository.write_markdown(updated)
        return str(self.repository.paths.markdown_file)

    def upsert_memory(
        self,
        content: str,
        category: str = "general",
        status: str = "confirmed",
        source_type: str = "tool_memory_write",
        session_key: str = "",
        confidence: float = 0.75,
        importance: float = 0.75,
    ) -> MemoryRecord:
        kind = self.kind_for_category(category)
        slot = self.slot_for(category, content)
        value = self.value_for(slot, content)
        fingerprint = self.fingerprint_for(kind, slot, value)
        now = self.now_iso()
        evidence_id = self.create_evidence(source_type, content, category, session_key)
        existing = None
        for record in self.load_latest_memories():
            if record.fingerprint == fingerprint and record.status != "archived":
                existing = record
                break
        if existing:
            updated = MemoryRecord.from_dict(existing.to_dict())
            updated.summary = self.summary_for(content)
            updated.last_seen_at = now
            updated.source_count += 1
            updated.confidence = round(max(updated.confidence, confidence), 4)
            updated.importance = round(max(updated.importance, importance), 4)
            updated.evidence_refs = self.dedupe(updated.evidence_refs + [evidence_id])
            if status == "confirmed":
                updated.status = "confirmed"
                updated.last_confirmed_at = now
            updated.conflicts_with = self.dedupe(updated.conflicts_with + self.find_conflicts(slot, value, updated.memory_id))
            self.repository.append_memory(updated)
            self.append_event("upserted", updated.memory_id, "same_fingerprint", existing.status, updated.status)
            
            self._index_memory_to_vector(updated)
            return updated

        conflicts = self.find_conflicts(slot, value)
        record = MemoryRecord(
            memory_id=self.new_id("mem"),
            kind=kind,
            scope="user",
            status="disputed" if conflicts and status == "confirmed" else status,
            slot=slot,
            value=value,
            summary=self.summary_for(content),
            confidence=round(confidence, 4),
            importance=round(importance, 4),
            stability="high" if kind in {"preference", "profile", "constraint"} else "medium",
            source_count=1,
            first_seen_at=now,
            last_seen_at=now,
            last_confirmed_at=now if status == "confirmed" else None,
            expires_at=None,
            tags=[kind, self.normalize_category(category)],
            evidence_refs=[evidence_id],
            supersedes=[],
            conflicts_with=conflicts,
            fingerprint=fingerprint,
        )
        self.repository.append_memory(record)
        self.append_event("created", record.memory_id, source_type, "", record.status)
        if conflicts:
            memory_map = self.load_memory_map()
            for conflict_id in conflicts:
                conflict = memory_map.get(conflict_id)
                if not conflict:
                    continue
                updated_conflict = MemoryRecord.from_dict(conflict.to_dict())
                updated_conflict.status = "disputed"
                updated_conflict.conflicts_with = self.dedupe(updated_conflict.conflicts_with + [record.memory_id])
                self.repository.append_memory(updated_conflict)
                self.append_event("disputed", conflict_id, "slot_value_conflict", conflict.status, "disputed")
        
        self._index_memory_to_vector(record)
        return record
    
    def _index_memory_to_vector(self, record: MemoryRecord) -> None:
        text = f"{record.summary}\n{record.value}".strip()
        if not text:
            return
        metadata = {
            "memory_id": record.memory_id,
            "kind": record.kind,
            "slot": record.slot,
            "status": record.status,
            "confidence": record.confidence,
            "importance": record.importance,
            "last_seen_at": record.last_seen_at,
        }
        self.vector_store.add(
            collection_name="memories",
            texts=[text],
            metadatas=[metadata],
            ids=[record.memory_id]
        )

    def ingest_user_message(self, content: str, session_key: str = "") -> list[MemoryRecord]:
        candidates: list[tuple[str, str]] = []
        lowered = content.lower()
        if ("中文" in content and "回答" in content) or "reply in chinese" in lowered:
            candidates.append(("language", "用户希望优先使用中文回答。"))
        if ("简洁" in content and "回答" in content) or "concise" in lowered:
            candidates.append(("preference", "用户偏好简洁回答。"))
        project_match = re.search(r"(我在做|正在做|working on|building)\s*[:：]?\s*(.+)", content, re.IGNORECASE)
        if project_match:
            candidates.append(("project", project_match.group(2).strip()))
        staged: list[MemoryRecord] = []
        for category, item in candidates:
            staged.append(
                self.upsert_memory(
                    item,
                    category=category,
                    status="candidate",
                    source_type="user_message",
                    session_key=session_key,
                    confidence=0.62,
                    importance=0.7 if category == "project" else 0.65,
                )
            )
        return staged

    def write_memory(self, content: str, category: str = "general") -> str:
        payload = {
            "ts": self.now_iso(),
            "category": category,
            "content": content,
        }
        try:
            self.repository.append_daily_entry(payload)
            record = self.upsert_memory(
                content,
                category=category,
                status="confirmed",
                source_type="tool_memory_write",
                confidence=0.88,
                importance=0.82,
            )
            self.sync_memory_markdown()
            day = payload["ts"][:10]
            return f"Memory saved to {day}.jsonl ({category}) | ledger={record.memory_id} status={record.status}"
        except Exception as exc:
            return f"Error writing memory: {exc}"

    def load_evergreen(self) -> str:
        return self.repository.read_markdown().strip()

    def raw_chunks(self) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        evergreen = self.load_evergreen()
        if evergreen:
            for paragraph in evergreen.split("\n\n"):
                paragraph = paragraph.strip()
                if paragraph:
                    chunks.append({"path": "MEMORY.md", "text": paragraph})
        for entry in self.repository.load_daily_entries():
            text = entry.get("content", "")
            if not text:
                continue
            category = entry.get("category", "")
            label = f"{entry['_path']} [{category}]" if category else entry["_path"]
            chunks.append({"path": label, "text": text})
        return chunks

    def ledger_chunks(self) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        for record in self.load_latest_memories():
            if record.status in {"archived", "expired"}:
                continue
            text = f"{record.summary}\n{record.value}".strip()
            if not text:
                continue
            chunks.append(
                {
                    "path": f"ledger:{record.kind}:{record.slot}",
                    "text": text,
                    "memory_id": record.memory_id,
                    "status": record.status,
                    "confidence": record.confidence,
                    "importance": record.importance,
                    "slot": record.slot,
                    "kind": record.kind,
                }
            )
        return chunks

    @staticmethod
    def status_weight(status: str) -> float:
        return {
            "confirmed": 1.2,
            "candidate": 0.95,
            "disputed": 0.7,
            "deprecated": 0.5,
            "expired": 0.4,
            "archived": 0.2,
        }.get(status, 0.85)

    def rank_chunks(self, query: str, chunks: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        return self.retriever.rank(query, chunks, top_k=top_k)

    def record_trace(self, query: str, results: list[dict[str, Any]]) -> None:
        trace = RetrievalTrace(
            trace_id=self.new_id("rt"),
            query=query,
            selected=[
                RetrievalTraceItem(
                    memory_id=result.get("memory_id"),
                    path=result["path"],
                    score=result["score"],
                    status=result["status"],
                    reason=result.get("reason", "hybrid_rank"),
                )
                for result in results
            ],
            created_at=self.now_iso(),
        )
        self.last_trace = trace
        self.repository.append_trace(trace)

    def hybrid_search(self, query: str, top_k: int = 5, use_vector: bool = True) -> list[dict[str, Any]]:
        ledger_ranked = self.rank_chunks(query, self.ledger_chunks(), top_k=max(top_k * 2, 6))
        raw_ranked = self.rank_chunks(query, self.raw_chunks(), top_k=max(top_k * 2, 6))
        results: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for ranked in ledger_ranked:
            chunk = ranked["chunk"]
            score = ranked["score"]
            score *= self.status_weight(chunk.get("status", "candidate"))
            score *= 0.8 + 0.2 * float(chunk.get("confidence", 0.0))
            score *= 0.8 + 0.2 * float(chunk.get("importance", 0.0))
            snippet = chunk["text"][:200] + ("..." if len(chunk["text"]) > 200 else "")
            key = f"mem:{chunk.get('memory_id')}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            results.append(
                {
                    "memory_id": chunk.get("memory_id"),
                    "path": chunk["path"],
                    "score": round(score, 4),
                    "snippet": snippet,
                    "status": chunk.get("status"),
                    "reason": "ledger_hybrid",
                }
            )
        for ranked in raw_ranked:
            chunk = ranked["chunk"]
            snippet = chunk["text"][:200] + ("..." if len(chunk["text"]) > 200 else "")
            key = f"raw:{chunk['path']}:{snippet}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            results.append(
                {
                    "memory_id": None,
                    "path": chunk["path"],
                    "score": round(ranked["score"], 4),
                    "snippet": snippet,
                    "status": "raw",
                    "reason": "raw_hybrid",
                }
            )
        
        if use_vector:
            try:
                vector_results = self.vector_store.search("memories", query, top_k=max(top_k * 2, 6))
                for vr in vector_results:
                    key = f"vec:{vr['id']}"
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    metadata = vr.get("metadata", {})
                    score = vr["score"]
                    if metadata.get("status"):
                        score *= self.status_weight(metadata.get("status", "candidate"))
                    score *= 0.8 + 0.2 * float(metadata.get("confidence", 0.0))
                    score *= 0.8 + 0.2 * float(metadata.get("importance", 0.0))
                    snippet = vr["text"][:200] + ("..." if len(vr["text"]) > 200 else "")
                    results.append(
                        {
                            "memory_id": metadata.get("memory_id") or vr["id"],
                            "path": f"vec:{metadata.get('kind', 'general')}:{metadata.get('slot', 'general')}",
                            "score": round(score, 4),
                            "snippet": snippet,
                            "status": metadata.get("status"),
                            "reason": "vector_search",
                        }
                    )
            except Exception as e:
                pass
        
        results.sort(key=lambda item: item["score"], reverse=True)
        selected = results[:top_k]
        self.record_trace(query, selected)
        return selected

    def list_memories(self, status: str = "", limit: int = 20) -> list[dict[str, Any]]:
        rows = self.load_latest_memories()
        if status:
            rows = [row for row in rows if row.status == status]
        rows.sort(key=lambda row: (row.last_seen_at, row.importance), reverse=True)
        return [row.to_dict() for row in rows[:limit]]

    def list_candidates(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.list_memories(status="candidate", limit=limit)

    def list_conflicts(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = [row for row in self.load_latest_memories() if row.status == "disputed" or row.conflicts_with]
        rows.sort(key=lambda row: row.last_seen_at, reverse=True)
        return [row.to_dict() for row in rows[:limit]]

    def confirm_memory(self, memory_id: str) -> tuple[bool, str]:
        record = self.load_memory_map().get(memory_id)
        if not record:
            return False, f"Memory not found: {memory_id}"
        if record.status == "confirmed":
            return True, f"Memory already confirmed: {memory_id}"
        updated = MemoryRecord.from_dict(record.to_dict())
        updated.status = "confirmed"
        updated.last_confirmed_at = self.now_iso()
        self.repository.append_memory(updated)
        self.append_event("confirmed", memory_id, "manual_confirm", record.status, "confirmed")
        self.sync_memory_markdown()
        return True, f"Memory confirmed: {memory_id}"

    def reject_memory(self, memory_id: str) -> tuple[bool, str]:
        record = self.load_memory_map().get(memory_id)
        if not record:
            return False, f"Memory not found: {memory_id}"
        if record.status == "archived":
            return True, f"Memory already archived: {memory_id}"
        updated = MemoryRecord.from_dict(record.to_dict())
        updated.status = "archived"
        updated.archived_at = self.now_iso()
        self.repository.append_memory(updated)
        self.append_event("rejected", memory_id, "manual_reject", record.status, "archived")
        self.sync_memory_markdown()
        return True, f"Memory rejected: {memory_id}"

    def forget_memory(self, memory_id: str) -> tuple[bool, str]:
        record = self.load_memory_map().get(memory_id)
        if not record:
            return False, f"Memory not found: {memory_id}"
        if record.status == "archived":
            return True, f"Memory already archived: {memory_id}"
        updated = MemoryRecord.from_dict(record.to_dict())
        updated.status = "archived"
        updated.archived_at = self.now_iso()
        self.repository.append_memory(updated)
        self.append_event("archived", memory_id, "manual_forget", record.status, "archived")
        self.sync_memory_markdown()
        return True, f"Memory archived: {memory_id}"

    def explain_memory(self, memory_id: str) -> str:
        record = self.load_memory_map().get(memory_id)
        if not record:
            return f"Memory not found: {memory_id}"
        evidence_rows = [
            row for row in self.repository.load_evidence()
            if row.get("evidence_id") in set(record.evidence_refs)
        ]
        event_rows = self.repository.load_events(memory_id=memory_id)
        lines = [
            f"memory_id: {record.memory_id}",
            f"status: {record.status}",
            f"kind: {record.kind}",
            f"slot: {record.slot}",
            f"value: {record.value}",
            f"summary: {record.summary}",
            f"confidence: {record.confidence}",
            f"importance: {record.importance}",
            f"source_count: {record.source_count}",
            f"conflicts_with: {', '.join(record.conflicts_with) if record.conflicts_with else '-'}",
            "evidence:",
        ]
        if evidence_rows:
            for row in evidence_rows:
                lines.append(
                    f"- {row.get('evidence_id')} [{row.get('source_type')}] {row.get('text_span', '')}"
                )
        else:
            lines.append("- (none)")
        lines.append("events:")
        if event_rows:
            for row in event_rows[-10:]:
                lines.append(
                    f"- {row.get('timestamp')} {row.get('action')} {row.get('from_status', '')}->{row.get('to_status', '')} reason={row.get('reason', '')}"
                )
        else:
            lines.append("- (none)")
        return "\n".join(lines)

    def format_last_trace(self) -> str:
        if not self.last_trace:
            return "(暂无 trace)"
        lines = [f"trace_id: {self.last_trace.trace_id}", f"query: {self.last_trace.query}"]
        for item in self.last_trace.selected:
            lines.append(
                f"- {item.path}  score={item.score}  status={item.status}  reason={item.reason}  memory_id={item.memory_id or '-'}"
            )
        return "\n".join(lines)

    def get_stats(self) -> dict[str, Any]:
        evergreen = self.load_evergreen()
        rows = self.load_latest_memories()
        return {
            "evergreen_chars": len(evergreen),
            "daily_files": len(list(self.repository.paths.daily_dir.glob('*.jsonl'))),
            "daily_entries": len(self.repository.load_daily_entries()),
            "ledger_total": len(rows),
            "ledger_confirmed": sum(1 for row in rows if row.status == "confirmed"),
            "ledger_candidate": sum(1 for row in rows if row.status == "candidate"),
            "ledger_disputed": sum(1 for row in rows if row.status == "disputed"),
            "ledger_review_pending": sum(1 for row in rows if row.status == "candidate"),
            "trace_count": self.repository.trace_count(),
            "managed_projection_path": str(self.repository.paths.markdown_file),
        }
