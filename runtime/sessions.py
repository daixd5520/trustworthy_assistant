from dataclasses import dataclass, field
from datetime import datetime, timezone


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
    def __init__(self) -> None:
        self._sessions: dict[str, SessionState] = {}

    @staticmethod
    def build_session_key(agent_id: str, channel: str = "terminal", user_id: str = "local") -> str:
        return f"agent:{agent_id}:{channel}:{user_id}"

    def get_or_create(self, agent_id: str, channel: str = "terminal", user_id: str = "local") -> SessionState:
        session_key = self.build_session_key(agent_id=agent_id, channel=channel, user_id=user_id)
        state = self._sessions.get(session_key)
        if state is None:
            state = SessionState(session_key=session_key, agent_id=agent_id, channel=channel, user_id=user_id)
            self._sessions[session_key] = state
        return state

    def append(self, session_key: str, role: str, content) -> None:
        session = self._sessions[session_key]
        session.messages.append({"role": role, "content": content})
        session.last_active_at = datetime.now(timezone.utc).isoformat()

    def list_sessions(self) -> list[dict]:
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
