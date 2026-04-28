from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class PersonalOpsService:
    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.base_dir = self.workspace_dir / "ops"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.commitments_file = self.base_dir / "commitments.jsonl"

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
                payload = json.loads(text)
                if isinstance(payload, dict):
                    rows.append(payload)
        except Exception:
            return []
        return rows

    def load_latest_commitments(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self._read_jsonl(self.commitments_file):
            commitment_id = str(row.get("commitment_id") or "").strip()
            if not commitment_id:
                continue
            latest[commitment_id] = row
        return list(latest.values())

    def _latest_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(row.get("commitment_id") or ""): row for row in self.load_latest_commitments()}

    def _get_commitment(self, commitment_id: str) -> dict[str, Any] | None:
        target = str(commitment_id or "").strip()
        if not target:
            return None
        return self._latest_by_id().get(target)

    def _write_updated(self, payload: dict[str, Any]) -> None:
        updated = dict(payload)
        updated["updated_at"] = _now_iso()
        self._append_jsonl(self.commitments_file, updated)

    def add_commitment(
        self,
        *,
        title: str,
        detail: str = "",
        due_at: str = "",
        agent_id: str,
        channel: str,
        user_id: str,
        source: str = "manual",
    ) -> dict[str, Any]:
        normalized_title = str(title or "").strip()
        if not normalized_title:
            raise ValueError("title must not be empty")
        payload = {
            "commitment_id": f"cmt_{uuid.uuid4().hex[:12]}",
            "title": normalized_title,
            "detail": str(detail or "").strip(),
            "due_at": str(due_at or "").strip(),
            "agent_id": str(agent_id or "").strip(),
            "channel": str(channel or "").strip(),
            "user_id": str(user_id or "").strip(),
            "status": "pending",
            "source": str(source or "manual").strip() or "manual",
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "completed_at": "",
            "expired_at": "",
            "block_reason": "",
            "dismiss_reason": "",
        }
        self._append_jsonl(self.commitments_file, payload)
        return payload

    def list_commitments(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        status: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = []
        for row in self.load_latest_commitments():
            if row.get("agent_id") != agent_id:
                continue
            if row.get("channel") != channel:
                continue
            if row.get("user_id") != user_id:
                continue
            if status and row.get("status") != status:
                continue
            rows.append(row)
        rows.sort(key=lambda item: (str(item.get("status") or ""), str(item.get("updated_at") or "")), reverse=True)
        return rows if limit <= 0 else rows[:limit]

    def complete_commitment(self, commitment_id: str) -> tuple[bool, str]:
        target = str(commitment_id or "").strip()
        if not target:
            return False, "commitment_id is required"
        current = self._get_commitment(target)
        if not current:
            return False, f"unknown commitment: {target}"
        updated = dict(current)
        updated["status"] = "completed"
        updated["completed_at"] = _now_iso()
        updated["block_reason"] = ""
        updated["dismiss_reason"] = ""
        self._write_updated(updated)
        return True, f"completed: {target}"

    def set_due_at(self, commitment_id: str, due_at: str) -> tuple[bool, str]:
        current = self._get_commitment(commitment_id)
        if not current:
            return False, f"unknown commitment: {commitment_id}"
        normalized_due_at = str(due_at or "").strip()
        if normalized_due_at and _parse_iso(normalized_due_at) is None:
            return False, "invalid due_at"
        updated = dict(current)
        updated["due_at"] = normalized_due_at
        self._write_updated(updated)
        return True, f"due_at updated: {commitment_id}"

    def block_commitment(self, commitment_id: str, *, reason: str = "") -> tuple[bool, str]:
        current = self._get_commitment(commitment_id)
        if not current:
            return False, f"unknown commitment: {commitment_id}"
        updated = dict(current)
        updated["status"] = "blocked"
        updated["block_reason"] = str(reason or "").strip()
        self._write_updated(updated)
        return True, f"blocked: {commitment_id}"

    def dismiss_commitment(self, commitment_id: str, *, reason: str = "") -> tuple[bool, str]:
        current = self._get_commitment(commitment_id)
        if not current:
            return False, f"unknown commitment: {commitment_id}"
        updated = dict(current)
        updated["status"] = "dismissed"
        updated["dismiss_reason"] = str(reason or "").strip()
        self._write_updated(updated)
        return True, f"dismissed: {commitment_id}"

    def expire_overdue_commitments(self, *, now_iso: str = "") -> dict[str, int]:
        now_dt = _parse_iso(now_iso) if now_iso else datetime.now().astimezone()
        if now_dt is None:
            raise ValueError("invalid now_iso")
        expired = 0
        for row in self.load_latest_commitments():
            if row.get("status") not in {"pending", "blocked"}:
                continue
            due_dt = _parse_iso(str(row.get("due_at") or ""))
            if due_dt is None or due_dt > now_dt:
                continue
            updated = dict(row)
            updated["status"] = "expired"
            updated["expired_at"] = now_dt.isoformat()
            self._write_updated(updated)
            expired += 1
        return {"expired": expired}

    @staticmethod
    def extract_candidate_commitments(text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        if not raw:
            return {"should_create_ops": False, "items": []}
        triggers = ["提醒我", "记得", "之后帮我", "回头", "先记一下", "下次继续", "帮我跟进", "明天", "今晚", "下周"]
        if not any(trigger in raw for trigger in triggers):
            return {"should_create_ops": False, "items": []}

        due_hint = ""
        if "明天" in raw:
            due_hint = "tomorrow"
        elif "今晚" in raw:
            due_hint = "tonight"
        elif "下周" in raw:
            due_hint = "next_week"

        title = raw
        replacements = [
            "明天提醒我看一下",
            "提醒我看一下",
            "提醒我",
            "记得",
            "之后帮我",
            "回头把",
            "回头",
            "先记一下",
            "下次继续",
            "帮我跟进",
            "今晚",
            "明天",
            "下周",
        ]
        for token in replacements:
            title = title.replace(token, "")
        title = re.sub(r"[，。,.!！?？]+", " ", title).strip()
        if "cron" in raw and "失败" in raw:
            title = "检查 cron 失败任务"
        elif "cron" in raw and "健康" in raw:
            title = "检查 cron 健康状态"
        elif "wecom" in raw.lower() and "重试" in raw:
            title = "补 wecom 重试策略"
        elif not title:
            return {"should_create_ops": False, "items": []}

        item = {
            "title": title,
            "detail": raw,
            "due_hint": due_hint,
            "reason": "检测到提醒、跟进或后续动作表达",
            "confidence": 0.82,
        }
        return {"should_create_ops": True, "items": [item]}

    @classmethod
    def format_extraction_result(cls, text: str) -> str:
        extracted = cls.extract_candidate_commitments(text)
        items = extracted.get("items") or []
        if not extracted.get("should_create_ops") or not items:
            return "Ops Extract Candidate\n- (未识别到可加入 ops 的事项)"
        lines = ["Ops Extract Candidate"]
        for item in items:
            lines.append(f"- title: {item.get('title','')}")
            if item.get("due_hint"):
                lines.append(f"  due_hint: {item.get('due_hint','')}")
            lines.append(f"  reason: {item.get('reason','')}")
            lines.append("  action: 如需写入，请使用 /ops add 或后续确认流。")
        return "\n".join(lines)

    def format_pending_context(self, *, agent_id: str, channel: str, user_id: str, limit: int = 5) -> str:
        rows = self.list_commitments(
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            status="pending",
            limit=limit,
        )
        if not rows:
            return ""
        lines = []
        for row in rows:
            detail = str(row.get("detail") or "").strip()
            due_at = str(row.get("due_at") or "").strip()
            line = f"- [{row.get('commitment_id','-')}] {row.get('title','')}"
            if due_at:
                line += f" | due={due_at}"
            if detail:
                line += f" | {detail}"
            lines.append(line)
        return "\n".join(lines)
