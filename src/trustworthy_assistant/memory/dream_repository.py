import json
from pathlib import Path
from typing import Any


class DreamRepository:
    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.base_dir = self.workspace_dir / "memory" / "dream"
        self.reports_dir = self.base_dir / "reports"
        self.plans_file = self.base_dir / "plans.jsonl"
        self.runs_file = self.base_dir / "runs.jsonl"
        self.lessons_file = self.base_dir / "lessons.jsonl"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        rows: list[dict[str, Any]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    rows.append(payload)
        except Exception:
            return []
        return rows

    def append_plan(self, payload: dict[str, Any]) -> None:
        self._append_jsonl(self.plans_file, payload)

    def append_run(self, payload: dict[str, Any]) -> None:
        self._append_jsonl(self.runs_file, payload)

    def append_lesson(self, payload: dict[str, Any]) -> None:
        self._append_jsonl(self.lessons_file, payload)

    def load_latest_plans(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self._read_jsonl(self.plans_file):
            plan_id = str(row.get("plan_id") or "").strip()
            if not plan_id:
                continue
            latest[plan_id] = row
        return list(latest.values())

    @staticmethod
    def _plan_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(row.get("updated_at") or ""),
            str(row.get("created_at") or ""),
            str(row.get("scheduled_for") or ""),
        )

    def load_plans(
        self,
        *,
        agent_id: str = "",
        channel: str = "",
        user_id: str = "",
        target_date: str = "",
        status: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.load_latest_plans()
        filtered: list[dict[str, Any]] = []
        for row in rows:
            if agent_id and row.get("agent_id") != agent_id:
                continue
            if channel and row.get("channel") != channel:
                continue
            if user_id and row.get("user_id") != user_id:
                continue
            if target_date and row.get("target_date") != target_date:
                continue
            if status and row.get("status") != status:
                continue
            filtered.append(row)
        filtered.sort(key=lambda item: str(item.get("scheduled_for") or ""), reverse=True)
        if limit > 0:
            filtered = filtered[:limit]
        return filtered

    def find_plan(self, *, agent_id: str, channel: str, user_id: str, target_date: str) -> dict[str, Any] | None:
        matched = [
            row
            for row in self.load_latest_plans()
            if row.get("agent_id") == agent_id
            and row.get("channel") == channel
            and row.get("user_id") == user_id
            and row.get("target_date") == target_date
        ]
        if not matched:
            return None
        matched.sort(key=self._plan_sort_key, reverse=True)
        return matched[0]

    def load_runs(
        self,
        *,
        agent_id: str = "",
        channel: str = "",
        user_id: str = "",
        target_date: str = "",
        status: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self._read_jsonl(self.runs_file)
        filtered: list[dict[str, Any]] = []
        for row in rows:
            if agent_id and row.get("agent_id") != agent_id:
                continue
            if channel and row.get("channel") != channel:
                continue
            if user_id and row.get("user_id") != user_id:
                continue
            if target_date and row.get("target_date") != target_date:
                continue
            if status and row.get("status") != status:
                continue
            filtered.append(row)
        filtered.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        if limit > 0:
            filtered = filtered[:limit]
        return filtered

    def load_latest_lessons(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self._read_jsonl(self.lessons_file):
            lesson_id = str(row.get("lesson_id") or "").strip()
            if not lesson_id:
                continue
            latest[lesson_id] = row
        return list(latest.values())

    def load_lessons(
        self,
        *,
        agent_id: str = "",
        channel: str = "",
        user_id: str = "",
        status: str = "active",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = self.load_latest_lessons()
        filtered: list[dict[str, Any]] = []
        for row in rows:
            if agent_id and row.get("agent_id") not in {"", agent_id}:
                continue
            if channel and row.get("channel") not in {"", channel}:
                continue
            if user_id and row.get("user_id") not in {"", user_id}:
                continue
            if status and row.get("status") != status:
                continue
            filtered.append(row)
        filtered.sort(
            key=lambda item: (
                float(item.get("importance") or 0.0),
                str(item.get("last_seen_at") or ""),
            ),
            reverse=True,
        )
        if limit > 0:
            filtered = filtered[:limit]
        return filtered

    def write_report(self, *, target_date: str, scope_key: str, content: str) -> str:
        report_dir = self.reports_dir / target_date
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{scope_key}.md"
        report_path.write_text(content, encoding="utf-8")
        return str(report_path)

    def read_report(self, report_path: str) -> str:
        path = Path(report_path)
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""
