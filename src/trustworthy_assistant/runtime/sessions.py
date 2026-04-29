import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SessionState:
    session_key: str
    agent_id: str
    channel: str
    user_id: str
    messages: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SessionManager:
    def __init__(
        self,
        *,
        state_file: Path | None = None,
        max_messages_per_session: int = 200,
        max_chars_per_session: int = 120_000,
    ) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, SessionState] = {}
        self._state_file = Path(state_file) if state_file else None
        self._max_messages_per_session = max(1, int(max_messages_per_session))
        self._max_chars_per_session = max(1_000, int(max_chars_per_session))
        self._load_state()

    @staticmethod
    def build_session_key(agent_id: str, channel: str = "terminal", user_id: str = "local") -> str:
        return f"agent:{agent_id}:{channel}:{user_id}"

    def get_or_create(self, agent_id: str, channel: str = "terminal", user_id: str = "local") -> SessionState:
        with self._lock:
            session_key = self.build_session_key(agent_id=agent_id, channel=channel, user_id=user_id)
            state = self._sessions.get(session_key)
            if state is None:
                state = SessionState(session_key=session_key, agent_id=agent_id, channel=channel, user_id=user_id)
                self._sessions[session_key] = state
                self._save_state()
            return state

    def append(self, session_key: str, role: str, content) -> None:
        with self._lock:
            session = self._sessions[session_key]
            session.messages.append({"role": str(role), "content": self._normalize_content(content)})
            session.last_active_at = datetime.now(timezone.utc).isoformat()
            self._trim_session(session)
            self._save_state()

    def list_sessions(self) -> list[dict]:
        with self._lock:
            rows = []
            for state in self._sessions.values():
                rows.append(
                    {
                        "session_key": state.session_key,
                        "agent_id": state.agent_id,
                        "channel": state.channel,
                        "user_id": state.user_id,
                        "message_count": len(state.messages),
                        "last_active_at": state.last_active_at,
                    }
                )
        rows.sort(key=lambda row: row["last_active_at"], reverse=True)
        return rows

    def _trim_session(self, session: SessionState) -> None:
        while len(session.messages) > self._max_messages_per_session:
            session.messages.pop(0)
        while len(session.messages) > 1 and self._session_char_count(session) > self._max_chars_per_session:
            session.messages.pop(0)

    def _session_char_count(self, session: SessionState) -> int:
        total = 0
        for message in session.messages:
            total += len(str(message.get("role", "")))
            total += self._estimate_chars(message.get("content"))
        return total

    def _estimate_chars(self, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            return len(value)
        try:
            return len(json.dumps(value, ensure_ascii=False))
        except TypeError:
            return len(str(value))

    def _normalize_content(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, list):
            return [self._normalize_content(item) for item in value]
        if isinstance(value, tuple):
            return [self._normalize_content(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._normalize_content(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            try:
                return self._normalize_content(value.model_dump(mode="json"))
            except TypeError:
                return self._normalize_content(value.model_dump())
        if hasattr(value, "dict"):
            try:
                return self._normalize_content(value.dict())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            try:
                return self._normalize_content(
                    {
                        key: item
                        for key, item in vars(value).items()
                        if not str(key).startswith("_")
                    }
                )
            except Exception:
                pass
        return str(value)

    def _load_state(self) -> None:
        if self._state_file is None or not self._state_file.is_file():
            return
        try:
            payload = json.loads(self._state_file.read_text(encoding="utf-8"))
        except Exception:
            return
        rows = payload.get("sessions")
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            session_key = str(row.get("session_key") or "").strip()
            if not session_key:
                continue
            state = SessionState(
                session_key=session_key,
                agent_id=str(row.get("agent_id") or ""),
                channel=str(row.get("channel") or "terminal"),
                user_id=str(row.get("user_id") or "local"),
                created_at=str(row.get("created_at") or datetime.now(timezone.utc).isoformat()),
                last_active_at=str(row.get("last_active_at") or datetime.now(timezone.utc).isoformat()),
            )
            raw_messages = row.get("messages")
            if isinstance(raw_messages, list):
                for message in raw_messages:
                    if not isinstance(message, dict):
                        continue
                    state.messages.append(
                        {
                            "role": str(message.get("role") or ""),
                            "content": self._normalize_content(message.get("content")),
                        }
                    )
            self._trim_session(state)
            self._sessions[session_key] = state

    def _save_state(self) -> None:
        if self._state_file is None:
            return
        payload = {
            "sessions": [
                {
                    "session_key": state.session_key,
                    "agent_id": state.agent_id,
                    "channel": state.channel,
                    "user_id": state.user_id,
                    "messages": state.messages,
                    "created_at": state.created_at,
                    "last_active_at": state.last_active_at,
                }
                for state in self._sessions.values()
            ]
        }
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            return
