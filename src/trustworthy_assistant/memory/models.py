from dataclasses import asdict, dataclass, field


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    kind: str
    scope: str
    status: str
    slot: str
    value: str
    summary: str
    confidence: float
    importance: float
    stability: str
    source_count: int
    first_seen_at: str
    last_seen_at: str
    last_confirmed_at: str | None
    expires_at: str | None
    tags: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    conflicts_with: list[str] = field(default_factory=list)
    fingerprint: str = ""
    archived_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict) -> "MemoryRecord":
        return cls(
            memory_id=payload["memory_id"],
            kind=payload.get("kind", "general"),
            scope=payload.get("scope", "user"),
            status=payload.get("status", "candidate"),
            slot=payload.get("slot", "general"),
            value=payload.get("value", ""),
            summary=payload.get("summary", ""),
            confidence=float(payload.get("confidence", 0.0)),
            importance=float(payload.get("importance", 0.0)),
            stability=payload.get("stability", "medium"),
            source_count=int(payload.get("source_count", 1)),
            first_seen_at=payload.get("first_seen_at", ""),
            last_seen_at=payload.get("last_seen_at", ""),
            last_confirmed_at=payload.get("last_confirmed_at"),
            expires_at=payload.get("expires_at"),
            tags=list(payload.get("tags", [])),
            evidence_refs=list(payload.get("evidence_refs", [])),
            supersedes=list(payload.get("supersedes", [])),
            conflicts_with=list(payload.get("conflicts_with", [])),
            fingerprint=payload.get("fingerprint", ""),
            archived_at=payload.get("archived_at"),
        )


@dataclass(slots=True)
class EvidenceRecord:
    evidence_id: str
    source_type: str
    category: str
    session_key: str
    text_span: str
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class MemoryEvent:
    event_id: str
    memory_id: str
    action: str
    reason: str
    from_status: str
    to_status: str
    timestamp: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class RetrievalTraceItem:
    memory_id: str | None
    path: str
    score: float
    status: str
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class RetrievalTrace:
    trace_id: str
    query: str
    selected: list[RetrievalTraceItem]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "query": self.query,
            "selected": [item.to_dict() for item in self.selected],
            "created_at": self.created_at,
        }
