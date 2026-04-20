from __future__ import annotations

import json
import random
import re
import uuid
from datetime import date, datetime, time as dt_time, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from anthropic import Anthropic
except Exception:  # pragma: no cover - allows logic tests without runtime deps
    Anthropic = None  # type: ignore[assignment]

from trustworthy_assistant.memory.dream_repository import DreamRepository
from trustworthy_assistant.memory.service import TrustworthyMemoryService


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _sanitize_scope_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "").strip()).strip("-")
    return cleaned or fallback


def _resolve_tz(tz_name: str):
    if not tz_name or tz_name.lower() == "local":
        return _local_now().tzinfo
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return _local_now().tzinfo


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        payload = json.loads(raw[start : end + 1])
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


class DreamService:
    def __init__(
        self,
        *,
        workspace_dir: Path,
        memory_service: TrustworthyMemoryService,
        client: Any | None,
        model_id: str,
        enabled: bool = True,
        min_digest_count: int = 3,
        min_digest_chars: int = 300,
        window_start_hour: int = 3,
        window_end_hour: int = 8,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.memory_service = memory_service
        self.client = client
        self.model_id = model_id
        self.enabled = enabled
        self.min_digest_count = max(1, int(min_digest_count))
        self.min_digest_chars = max(0, int(min_digest_chars))
        self.window_start_hour = max(0, min(int(window_start_hour), 23))
        self.window_end_hour = max(self.window_start_hour + 1, min(int(window_end_hour), 24))
        self.on_event = on_event or (lambda _message: None)
        self.repository = DreamRepository(self.workspace_dir)
        self.cron_file = self.workspace_dir / "CRON.json"

    @staticmethod
    def _maintenance_job_id() -> str:
        return "dream-maintain-lessons"

    @staticmethod
    def _allowed_memory_categories() -> set[str]:
        return {"project", "language", "response_style", "constraint", "decision"}

    @staticmethod
    def _contains_sensitive_content(text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        lowered = value.lower()
        patterns = [
            r"\b(?:password|passwd|otp|验证码|口令|密钥|token|api[-_ ]?key)\b",
            r"\b\d{15,19}\b",
            r"\b1\d{10}\b",
            r"\b\d{17}[\dxX]\b",
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            r"\b(?:身份证|银行卡|住址|家庭住址|详细地址|护照|社保号)\b",
        ]
        return any(re.search(pattern, value) for pattern in patterns) or any(
            keyword in lowered
            for keyword in ["private key", "secret key", "seed phrase", "recovery code"]
        )

    def next_retry_time(self, *, scheduled_for: datetime, tz_name: str = "Local", retry_count: int = 1) -> datetime | None:
        base = scheduled_for.astimezone(_resolve_tz(tz_name))
        delay_minutes = min(15 * max(retry_count, 1), 60)
        retry_local = base + timedelta(minutes=delay_minutes)
        deadline_local = datetime.combine(
            base.date(),
            dt_time(hour=self.window_end_hour, minute=0, second=0),
            tzinfo=base.tzinfo,
        )
        if retry_local >= deadline_local:
            return None
        return retry_local.astimezone(timezone.utc)

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _scope_key(agent_id: str, channel: str, user_id: str) -> str:
        return "-".join(
            [
                _sanitize_scope_component(agent_id, "agent"),
                _sanitize_scope_component(channel, "channel"),
                _sanitize_scope_component(user_id, "user"),
            ]
        )

    @staticmethod
    def _normalize_lesson_text(text: str) -> str:
        return re.sub(r"[\W_]+", "", str(text or "").lower())

    @classmethod
    def _lesson_similarity(cls, left: str, right: str) -> float:
        a = cls._normalize_lesson_text(left)
        b = cls._normalize_lesson_text(right)
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if a in b or b in a:
            return 0.9
        return SequenceMatcher(a=a, b=b).ratio()

    def resolve_target_date(self, selector: str = "") -> str:
        value = str(selector or "").strip().lower()
        if not value or value == "today":
            return self.memory_service.local_day_key()
        if value == "yesterday":
            return (date.today() - timedelta(days=1)).isoformat()
        return date.fromisoformat(selector.strip()).isoformat()

    def has_enough_activity(self, *, agent_id: str, channel: str, user_id: str, local_date: str) -> bool:
        rows = self.memory_service.load_daily_digests(
            local_date=local_date,
            channel=channel,
            user_id=user_id,
            agent_id=agent_id,
            limit=0,
        )
        if len(rows) >= self.min_digest_count:
            return True
        total_chars = sum(len(str(row.get("summary") or "")) for row in rows)
        return total_chars >= self.min_digest_chars

    def pick_schedule_time(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str,
        tz_name: str = "Local",
    ) -> datetime:
        target = date.fromisoformat(target_date) + timedelta(days=1)
        tz = _resolve_tz(tz_name)
        seed = f"{agent_id}|{channel}|{user_id}|{target_date}"
        rng = random.Random(seed)
        hour = rng.randint(self.window_start_hour, self.window_end_hour - 1)
        minute = rng.randint(0, 59)
        second = rng.randint(0, 59)
        return datetime.combine(target, dt_time(hour=hour, minute=minute, second=second), tzinfo=tz)

    def ensure_plan(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        local_date: str,
        tz_name: str = "Local",
    ) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        if channel == "cron" or not user_id:
            return None
        existing = self.repository.find_plan(
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            target_date=local_date,
        )
        if existing and existing.get("status") in {"scheduled", "running", "completed"}:
            return existing
        if not self.has_enough_activity(agent_id=agent_id, channel=channel, user_id=user_id, local_date=local_date):
            return None
        scheduled_for = self.pick_schedule_time(
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            target_date=local_date,
            tz_name=tz_name,
        )
        scope_key = self._scope_key(agent_id, channel, user_id)
        plan_id = self._new_id("dream_plan")
        job_id = f"dream-{scope_key}-{local_date}"
        plan = {
            "plan_id": plan_id,
            "agent_id": agent_id,
            "channel": channel,
            "user_id": user_id,
            "target_date": local_date,
            "scheduled_for": scheduled_for.isoformat(),
            "job_id": job_id,
            "status": "scheduled",
            "created_at": _local_now().isoformat(),
        }
        self.repository.append_plan(plan)
        self._upsert_cron_job(
            job_id=job_id,
            schedule_at=scheduled_for,
            plan_id=plan_id,
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            target_date=local_date,
            tz_name=tz_name,
        )
        self.on_event(f"dream planned: {job_id} for {scheduled_for.isoformat()}")
        return plan

    def _upsert_cron_job(
        self,
        *,
        job_id: str,
        schedule_at: datetime,
        plan_id: str,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str,
        tz_name: str,
    ) -> None:
        data = {"jobs": []}
        if self.cron_file.is_file():
            try:
                parsed = json.loads(self.cron_file.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                data = {"jobs": []}
        jobs = data.get("jobs")
        rows = jobs if isinstance(jobs, list) else []
        indexed = {str(job.get("id") or ""): job for job in rows if isinstance(job, dict)}
        indexed[job_id] = {
            "id": job_id,
            "name": "Nightly Dream",
            "enabled": True,
            "schedule": {
                "kind": "cron",
                "expr": f"{schedule_at.minute} {schedule_at.hour} {schedule_at.day} {schedule_at.month} *",
                "tz": tz_name or "Local",
            },
            "payload": {
                "kind": "dream_run",
                "plan_id": plan_id,
                "agent_id": agent_id,
                "channel": channel,
                "user_id": user_id,
                "target_date": target_date,
                "tz": tz_name or "Local",
            },
            "delete_after_run": True,
        }
        merged_jobs = list(indexed.values())
        merged_jobs.sort(key=lambda item: str(item.get("id") or ""))
        data["jobs"] = merged_jobs
        self.cron_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def ensure_maintenance_job(self, *, tz_name: str = "Local", hour: int = 5, minute: int = 40) -> None:
        data = {"jobs": []}
        if self.cron_file.is_file():
            try:
                parsed = json.loads(self.cron_file.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                data = {"jobs": []}
        jobs = data.get("jobs")
        rows = jobs if isinstance(jobs, list) else []
        indexed = {str(job.get("id") or ""): job for job in rows if isinstance(job, dict)}
        indexed[self._maintenance_job_id()] = {
            "id": self._maintenance_job_id(),
            "name": "Dream Lesson Maintenance",
            "enabled": True,
            "schedule": {
                "kind": "cron",
                "expr": f"{minute} {hour} * * *",
                "tz": tz_name or "Local",
            },
            "payload": {
                "kind": "dream_maintain",
            },
            "delete_after_run": False,
        }
        merged_jobs = list(indexed.values())
        merged_jobs.sort(key=lambda item: str(item.get("id") or ""))
        data["jobs"] = merged_jobs
        self.cron_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def mark_plan_status(self, plan: dict[str, Any], status: str, *, error: str = "", run_id: str = "") -> dict[str, Any]:
        updated = dict(plan)
        updated["status"] = status
        updated["updated_at"] = _local_now().isoformat()
        if error:
            updated["last_error"] = error
        if run_id:
            updated["last_run_id"] = run_id
        self.repository.append_plan(updated)
        return updated

    def run_once(
        self,
        *,
        plan_id: str,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str,
    ) -> dict[str, Any]:
        plan = self.repository.find_plan(
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            target_date=target_date,
        ) or {
            "plan_id": plan_id,
            "agent_id": agent_id,
            "channel": channel,
            "user_id": user_id,
            "target_date": target_date,
            "status": "scheduled",
        }
        run_id = self._new_id("dream_run")
        started_at = _local_now().isoformat()
        self.mark_plan_status(plan, "running", run_id=run_id)
        try:
            digests = self.memory_service.load_daily_digests(
                local_date=target_date,
                channel=channel,
                user_id=user_id,
                agent_id=agent_id,
                limit=0,
            )
            scoped_memories = self.memory_service.list_memories(
                limit=50,
                agent_id=agent_id,
                channel=channel,
                user_id=user_id,
            )
            synthesis = self.synthesize(
                agent_id=agent_id,
                channel=channel,
                user_id=user_id,
                target_date=target_date,
                digests=digests,
                memories=scoped_memories,
            )
            persisted = self.persist_result(
                agent_id=agent_id,
                channel=channel,
                user_id=user_id,
                target_date=target_date,
                synthesis=synthesis,
            )
            report = self.render_report(
                agent_id=agent_id,
                channel=channel,
                user_id=user_id,
                target_date=target_date,
                digests=digests,
                synthesis=synthesis,
                persisted=persisted,
            )
            report_path = self.repository.write_report(
                target_date=target_date,
                scope_key=self._scope_key(agent_id, channel, user_id),
                content=report,
            )
            finished_at = _local_now().isoformat()
            run = {
                "run_id": run_id,
                "plan_id": plan_id,
                "agent_id": agent_id,
                "channel": channel,
                "user_id": user_id,
                "target_date": target_date,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": "ok",
                "report_path": report_path,
                "new_memory_count": persisted["new_memory_count"],
                "new_lesson_count": persisted["new_lesson_count"],
                "error": "",
            }
            self.repository.append_run(run)
            self.mark_plan_status(plan, "completed", run_id=run_id)
            return run
        except Exception as exc:
            finished_at = _local_now().isoformat()
            run = {
                "run_id": run_id,
                "plan_id": plan_id,
                "agent_id": agent_id,
                "channel": channel,
                "user_id": user_id,
                "target_date": target_date,
                "started_at": started_at,
                "finished_at": finished_at,
                "status": "error",
                "report_path": "",
                "new_memory_count": 0,
                "new_lesson_count": 0,
                "error": str(exc),
            }
            self.repository.append_run(run)
            self.mark_plan_status(plan, "failed", error=str(exc), run_id=run_id)
            raise

    def run_manual(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str = "",
    ) -> dict[str, Any]:
        resolved_date = self.resolve_target_date(target_date)
        existing = self.repository.find_plan(
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            target_date=resolved_date,
        )
        if existing is None:
            plan = {
                "plan_id": self._new_id("dream_plan"),
                "agent_id": agent_id,
                "channel": channel,
                "user_id": user_id,
                "target_date": resolved_date,
                "scheduled_for": _local_now().isoformat(),
                "job_id": f"manual-dream-{self._scope_key(agent_id, channel, user_id)}-{resolved_date}",
                "status": "manual_requested",
                "created_at": _local_now().isoformat(),
            }
            self.repository.append_plan(plan)
            existing = plan
        return self.run_once(
            plan_id=str(existing.get("plan_id") or self._new_id("dream_plan")),
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            target_date=resolved_date,
        )

    def synthesize(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str,
        digests: list[dict[str, Any]],
        memories: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not digests:
            return {
                "topics": [],
                "user_memories": [],
                "agent_lessons": [],
                "conflicts": [],
                "open_questions": ["当天没有可整理的对话摘要。"],
            }
        payload = self._synthesize_via_model(
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            target_date=target_date,
            digests=digests,
            memories=memories,
        )
        if payload is None:
            payload = self._synthesize_fallback(target_date=target_date, digests=digests)
        return self._normalize_synthesis_payload(payload)

    def _synthesize_via_model(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str,
        digests: list[dict[str, Any]],
        memories: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if self.client is None:
            return None
        digest_lines: list[str] = []
        for index, row in enumerate(digests[-20:], start=1):
            digest_lines.append(
                f"{index}. ts={row.get('ts','')} summary={row.get('summary','')}"
            )
        memory_lines: list[str] = []
        for row in memories[:12]:
            memory_lines.append(
                f"- [{row.get('status','candidate')}] {row.get('slot','general')}: {row.get('summary','')}"
            )
        user_prompt = (
            "请对同一用户同一天的对话摘要做夜间记忆整理，并返回严格 JSON。"
            "\n要求："
            "\n1. `user_memories` 只保留较稳定、值得长期记住的内容。"
            "\n2. `agent_lessons` 只写关于服务方式的经验，不写用户事实。"
            "\n3. `status` 默认为 `candidate`，除非非常稳定才可给 `confirmed`。"
            "\n4. 不要输出 markdown，不要解释。"
            "\n5. 严格使用以下顶层字段：topics,user_memories,agent_lessons,conflicts,open_questions。"
            f"\n\nagent_id={agent_id} channel={channel} user_id={user_id} target_date={target_date}"
            "\n\n当天 digests:\n"
            + "\n".join(digest_lines)
            + "\n\n已有记忆:\n"
            + ("\n".join(memory_lines) if memory_lines else "(none)")
            + "\n\n返回 JSON schema 示例："
            '\n{"topics":[{"title":"","summary":"","evidence_count":1,"stability":"medium"}],'
            '"user_memories":[{"content":"","category":"project","status":"candidate","confidence":0.7,"importance":0.8,"reason":""}],'
            '"agent_lessons":[{"kind":"workflow","content":"","status":"active","confidence":0.7,"importance":0.8,"reason":""}],'
            '"conflicts":[],"open_questions":[]}'
        )
        try:
            response = self.client.messages.create(
                model=self.model_id,
                max_tokens=2200,
                system=(
                    "You are a memory consolidation engine. "
                    "Return strict JSON only. No markdown fences. No prose."
                ),
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception:
            return None
        text = "\n".join(
            getattr(block, "text", "")
            for block in getattr(response, "content", []) or []
            if getattr(block, "text", "")
        ).strip()
        return _extract_json_object(text)

    def _synthesize_fallback(self, *, target_date: str, digests: list[dict[str, Any]]) -> dict[str, Any]:
        combined = "；".join(str(row.get("summary") or "").strip() for row in digests[-6:] if row.get("summary"))
        summary = self.memory_service.summary_for(combined or f"{target_date} 当天有若干对话摘要。", limit=220)
        return {
            "topics": [
                {
                    "title": "daily_conversation_summary",
                    "summary": summary,
                    "evidence_count": len(digests),
                    "stability": "medium",
                }
            ],
            "user_memories": [],
            "agent_lessons": [],
            "conflicts": [],
            "open_questions": ["模型整理失败，已回退为基础摘要。"],
        }

    @staticmethod
    def _normalize_synthesis_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "topics": payload.get("topics") if isinstance(payload.get("topics"), list) else [],
            "user_memories": payload.get("user_memories") if isinstance(payload.get("user_memories"), list) else [],
            "agent_lessons": payload.get("agent_lessons") if isinstance(payload.get("agent_lessons"), list) else [],
            "conflicts": payload.get("conflicts") if isinstance(payload.get("conflicts"), list) else [],
            "open_questions": payload.get("open_questions") if isinstance(payload.get("open_questions"), list) else [],
        }
        return normalized

    def persist_result(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str,
        synthesis: dict[str, Any],
    ) -> dict[str, int]:
        new_memory_count = 0
        new_lesson_count = 0
        for item in synthesis.get("user_memories", []):
            content = str(item.get("content") or "").strip()
            category = str(item.get("category") or "general").strip().lower() or "general"
            if not content:
                continue
            confidence = float(item.get("confidence") or 0.68)
            importance = float(item.get("importance") or 0.78)
            if category not in self._allowed_memory_categories():
                continue
            if confidence < 0.72 or importance < 0.72:
                continue
            if len(content) > 240 or self._contains_sensitive_content(content):
                continue
            self.memory_service.upsert_memory(
                content,
                category=category,
                status="candidate",
                source_type="dreaming",
                session_key=f"dream:{agent_id}:{channel}:{user_id}:{target_date}",
                confidence=confidence,
                importance=importance,
                agent_id=agent_id,
                channel=channel,
                user_id=user_id,
            )
            new_memory_count += 1
        if new_memory_count:
            self.memory_service.sync_memory_markdown()
        for item in synthesis.get("agent_lessons", []):
            lesson = self._upsert_lesson(
                agent_id=agent_id,
                channel=channel,
                user_id=user_id,
                target_date=target_date,
                payload=item,
            )
            if lesson is not None:
                new_lesson_count += 1
        return {
            "new_memory_count": new_memory_count,
            "new_lesson_count": new_lesson_count,
        }

    def _upsert_lesson(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        content = str(payload.get("content") or "").strip()
        if not content:
            return None
        kind = str(payload.get("kind") or "workflow").strip() or "workflow"
        normalized_content = self._normalize_lesson_text(content)
        fingerprint = f"{agent_id}|{channel}|{user_id}|{kind}|{normalized_content}"
        existing = None
        for row in self.repository.load_lessons(agent_id=agent_id, channel=channel, user_id=user_id, status="", limit=0):
            if row.get("scope") != kind:
                continue
            existing_value = str(row.get("value") or "")
            similarity = self._lesson_similarity(existing_value, content)
            if row.get("fingerprint") == fingerprint or similarity >= 0.82:
                existing = row
                break
        now = _local_now().isoformat()
        if existing is None:
            lesson = {
                "lesson_id": self._new_id("lesson"),
                "agent_id": agent_id,
                "channel": channel,
                "user_id": user_id,
                "scope": kind,
                "status": str(payload.get("status") or "active").strip() or "active",
                "summary": self.memory_service.summary_for(content),
                "value": content,
                "confidence": round(float(payload.get("confidence") or 0.7), 4),
                "importance": round(float(payload.get("importance") or 0.78), 4),
                "evidence_refs": [f"dream:{target_date}"],
                "first_seen_at": now,
                "last_seen_at": now,
                "fingerprint": fingerprint,
            }
        else:
            lesson = dict(existing)
            lesson["summary"] = self.memory_service.summary_for(content)
            lesson["value"] = content
            lesson["last_seen_at"] = now
            lesson["confidence"] = round(max(float(existing.get("confidence") or 0.0), float(payload.get("confidence") or 0.7)), 4)
            lesson["importance"] = round(max(float(existing.get("importance") or 0.0), float(payload.get("importance") or 0.78)), 4)
            lesson["status"] = str(payload.get("status") or existing.get("status") or "active").strip() or "active"
            lesson["fingerprint"] = fingerprint
            refs = list(existing.get("evidence_refs") or [])
            refs.append(f"dream:{target_date}")
            deduped: list[str] = []
            seen: set[str] = set()
            for ref in refs:
                if ref in seen:
                    continue
                seen.add(ref)
                deduped.append(ref)
            lesson["evidence_refs"] = deduped
        self.repository.append_lesson(lesson)
        return lesson

    def render_report(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str,
        digests: list[dict[str, Any]],
        synthesis: dict[str, Any],
        persisted: dict[str, int],
    ) -> str:
        lines = [
            "# Nightly Dream Report",
            "",
            f"- Agent ID: `{agent_id}`",
            f"- Channel: `{channel}`",
            f"- User ID: `{user_id}`",
            f"- Target Date: `{target_date}`",
            f"- Digest Count: {len(digests)}",
            f"- Generated At: `{_local_now().isoformat()}`",
            "",
            "## Topics",
        ]
        topics = synthesis.get("topics", [])
        if topics:
            for topic in topics:
                lines.append(
                    f"- `{topic.get('title', 'topic')}` | evidence={topic.get('evidence_count', 0)} | "
                    f"stability={topic.get('stability', 'medium')} | {topic.get('summary', '').strip()}"
                )
        else:
            lines.append("- (none)")
        lines.extend(["", "## User Memories"])
        memories = synthesis.get("user_memories", [])
        if memories:
            for item in memories:
                lines.append(
                    f"- [{item.get('status', 'candidate')}] {item.get('category', 'general')} | "
                    f"confidence={item.get('confidence', 0)} importance={item.get('importance', 0)} | "
                    f"{item.get('content', '').strip()}"
                )
        else:
            lines.append("- (none)")
        lines.extend(["", "## Agent Lessons"])
        lessons = synthesis.get("agent_lessons", [])
        if lessons:
            for item in lessons:
                lines.append(
                    f"- [{item.get('status', 'active')}] {item.get('kind', 'workflow')} | "
                    f"confidence={item.get('confidence', 0)} importance={item.get('importance', 0)} | "
                    f"{item.get('content', '').strip()}"
                )
        else:
            lines.append("- (none)")
        lines.extend(["", "## Open Questions"])
        questions = synthesis.get("open_questions", [])
        if questions:
            for question in questions:
                lines.append(f"- {str(question).strip()}")
        else:
            lines.append("- (none)")
        lines.extend(
            [
                "",
                "## Persistence",
                "",
                f"- New Memories: {persisted.get('new_memory_count', 0)}",
                f"- New Lessons: {persisted.get('new_lesson_count', 0)}",
                "",
                "## Digest Samples",
            ]
        )
        if digests:
            for row in digests[-10:]:
                lines.append(f"- {row.get('ts', '')} | {row.get('summary', '').strip()}")
        else:
            lines.append("- (none)")
        return "\n".join(lines) + "\n"

    def search_lessons(self, query: str, *, agent_id: str, channel: str, user_id: str, top_k: int = 3) -> list[dict[str, Any]]:
        rows = self.repository.load_lessons(agent_id=agent_id, channel=channel, user_id=user_id, status="active", limit=50)
        if not rows:
            return []
        chunks: list[dict[str, Any]] = []
        for row in rows:
            text = f"{row.get('summary','')}\n{row.get('value','')}".strip()
            if not text:
                continue
            chunks.append(
                {
                    "path": f"lesson:{row.get('scope', 'workflow')}",
                    "text": text,
                    "status": row.get("status", "active"),
                    "importance": float(row.get("importance") or 0.0),
                    "confidence": float(row.get("confidence") or 0.0),
                    "lesson_id": row.get("lesson_id"),
                    "summary": row.get("summary", ""),
                }
            )
        ranked = self.memory_service.rank_chunks(query, chunks, top_k=max(top_k, 1))
        selected: list[dict[str, Any]] = []
        for item in ranked[:top_k]:
            chunk = item["chunk"]
            selected.append(
                {
                    "lesson_id": chunk.get("lesson_id"),
                    "path": chunk["path"],
                    "score": round(float(item["score"]), 4),
                    "summary": chunk.get("summary", ""),
                    "value": chunk["text"],
                }
            )
        return selected

    def format_lessons_context(self, query: str, *, agent_id: str, channel: str, user_id: str, top_k: int = 3) -> str:
        rows = self.search_lessons(query, agent_id=agent_id, channel=channel, user_id=user_id, top_k=top_k)
        if not rows:
            return ""
        return "\n".join(
            f"- [{row['path']}] (score={row['score']}) {self.memory_service.summary_for(row['value'], limit=180)}"
            for row in rows
        )

    def get_report(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        target_date: str = "",
    ) -> dict[str, Any] | None:
        resolved_date = self.resolve_target_date(target_date) if target_date else ""
        runs = self.repository.load_runs(
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            target_date=resolved_date,
            limit=20,
        )
        for run in runs:
            report_path = str(run.get("report_path") or "").strip()
            if not report_path:
                continue
            content = self.repository.read_report(report_path)
            if not content:
                continue
            return {
                "target_date": run.get("target_date", ""),
                "report_path": report_path,
                "content": content,
                "run": run,
            }
        if target_date:
            report_path = str(
                self.repository.reports_dir
                / self.resolve_target_date(target_date)
                / f"{self._scope_key(agent_id, channel, user_id)}.md"
            )
            content = self.repository.read_report(report_path)
            if content:
                return {
                    "target_date": self.resolve_target_date(target_date),
                    "report_path": report_path,
                    "content": content,
                    "run": {},
                }
        return None

    def prune_lessons(
        self,
        *,
        agent_id: str,
        channel: str,
        user_id: str,
        stale_days: int = 30,
        archive_days: int = 90,
        decay_factor: float = 0.92,
    ) -> dict[str, int]:
        now = _local_now()
        decayed = 0
        archived = 0
        scanned = 0
        rows = self.repository.load_lessons(
            agent_id=agent_id,
            channel=channel,
            user_id=user_id,
            status="",
            limit=0,
        )
        for row in rows:
            if str(row.get("status") or "active") == "archived":
                continue
            last_seen_raw = str(row.get("last_seen_at") or row.get("first_seen_at") or "").strip()
            if not last_seen_raw:
                continue
            try:
                last_seen = datetime.fromisoformat(last_seen_raw)
            except ValueError:
                continue
            scanned += 1
            age_days = max(0, (now - last_seen).days)
            if age_days < stale_days:
                continue
            lesson = dict(row)
            if age_days >= archive_days:
                lesson["status"] = "archived"
                lesson["archived_at"] = now.isoformat()
                self.repository.append_lesson(lesson)
                archived += 1
                continue
            steps = max(1, age_days // stale_days)
            old_confidence = float(row.get("confidence") or 0.0)
            old_importance = float(row.get("importance") or 0.0)
            new_confidence = round(old_confidence * (decay_factor ** steps), 4)
            new_importance = round(old_importance * (decay_factor ** steps), 4)
            if abs(new_confidence - old_confidence) < 0.0001 and abs(new_importance - old_importance) < 0.0001:
                continue
            lesson["confidence"] = new_confidence
            lesson["importance"] = new_importance
            lesson["last_maintained_at"] = now.isoformat()
            if max(new_confidence, new_importance) < 0.35:
                lesson["status"] = "archived"
                lesson["archived_at"] = now.isoformat()
                archived += 1
            else:
                decayed += 1
            self.repository.append_lesson(lesson)
        return {
            "scanned": scanned,
            "decayed": decayed,
            "archived": archived,
        }

    def prune_all_lessons(
        self,
        *,
        stale_days: int = 30,
        archive_days: int = 90,
        decay_factor: float = 0.92,
    ) -> dict[str, int]:
        rows = self.repository.load_lessons(status="", limit=0)
        scopes: set[tuple[str, str, str]] = set()
        for row in rows:
            scopes.add(
                (
                    str(row.get("agent_id") or ""),
                    str(row.get("channel") or ""),
                    str(row.get("user_id") or ""),
                )
            )
        total = {"scanned": 0, "decayed": 0, "archived": 0, "scopes": len(scopes)}
        for agent_id, channel, user_id in scopes:
            summary = self.prune_lessons(
                agent_id=agent_id,
                channel=channel,
                user_id=user_id,
                stale_days=stale_days,
                archive_days=archive_days,
                decay_factor=decay_factor,
            )
            total["scanned"] += int(summary.get("scanned", 0))
            total["decayed"] += int(summary.get("decayed", 0))
            total["archived"] += int(summary.get("archived", 0))
        return total

    def list_plans(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.load_plans(limit=limit)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.load_runs(limit=limit)

    def list_lessons(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.repository.load_lessons(limit=limit)
