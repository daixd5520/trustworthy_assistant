import copy
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class CronJobState:
    job_id: str
    name: str
    enabled: bool
    expr: str
    tz_name: str
    payload_kind: str
    message: str
    agent_id: str
    delete_after_run: bool
    raw: dict
    next_run_at: str = ""
    last_run_at: str = ""
    last_status: str = "idle"
    last_error: str = ""
    last_result_preview: str = ""
    channel: str = ""
    sender_id: str = ""
    _next_run_dt: datetime | None = field(default=None, repr=False, compare=False)

    @property
    def signature(self) -> tuple:
        return (
            self.enabled,
            self.expr,
            self.tz_name,
            self.payload_kind,
            self.message,
            self.agent_id,
            self.delete_after_run,
            self.channel,
            self.sender_id,
        )


class CronScheduler:
    def __init__(
        self,
        workspace_dir: Path,
        agent_registry,
        turn_processor,
        dream_service=None,
        on_event: Callable[[str], None] | None = None,
        poll_seconds: float = 15.0,
        channel_sender: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.cron_file = self.workspace_dir / "CRON.json"
        self.state_file = self.workspace_dir / "cron_state.json"
        self.agent_registry = agent_registry
        self.turn_processor = turn_processor
        self.dream_service = dream_service
        self.on_event = on_event or (lambda _message: None)
        self.poll_seconds = poll_seconds
        self.channel_sender = channel_sender
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._jobs: dict[str, CronJobState] = {}

    def start(self) -> bool:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop_event.clear()
            self.reload_jobs()
            self._thread = threading.Thread(target=self._run_loop, name="trustworthy-cron", daemon=True)
            self._thread.start()
        self.on_event("scheduler started")
        return True

    def stop(self) -> bool:
        with self._lock:
            if not self._thread:
                return False
            thread = self._thread
            self._thread = None
        self._stop_event.set()
        thread.join(timeout=2.0)
        self.on_event("scheduler stopped")
        return True

    def reload_jobs(self) -> int:
        now = _now_utc()
        raw_jobs = self._read_jobs_file()
        with self._lock:
            previous = self._jobs
            updated: dict[str, CronJobState] = {}
            for raw in raw_jobs:
                job = self._build_job_state(raw)
                existing = previous.get(job.job_id)
                if existing and existing.signature == job.signature:
                    job.last_run_at = existing.last_run_at
                    job.last_status = existing.last_status
                    job.last_error = existing.last_error
                    job.last_result_preview = existing.last_result_preview
                    job._next_run_dt = existing._next_run_dt
                    job.next_run_at = existing.next_run_at
                else:
                    saved = self._load_job_state(job.job_id)
                    if saved:
                        job.last_run_at = saved.get("last_run_at", "")
                        job.last_status = saved.get("last_status", "idle")
                        job.last_error = saved.get("last_error", "")
                        job.last_result_preview = saved.get("last_result_preview", "")
                    job._next_run_dt = self._compute_next_run(job, now)
                    job.next_run_at = job._next_run_dt.isoformat() if job._next_run_dt else ""
                updated[job.job_id] = job
            for jid, job in previous.items():
                if jid.startswith("reminder-") and jid not in updated:
                    updated[jid] = job
            self._jobs = updated
            return len(updated)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            rows = [
                {
                    "job_id": job.job_id,
                    "name": job.name,
                    "enabled": job.enabled,
                    "expr": job.expr,
                    "tz": job.tz_name,
                    "agent_id": job.agent_id,
                    "next_run_at": job.next_run_at,
                    "last_run_at": job.last_run_at,
                    "last_status": job.last_status,
                    "last_error": job.last_error,
                    "delete_after_run": job.delete_after_run,
                    "channel": job.channel,
                    "sender_id": job.sender_id,
                }
                for job in self._jobs.values()
            ]
        rows.sort(key=lambda row: (row["next_run_at"] or "9999", row["job_id"]))
        return rows

    def run_job_now(self, job_id: str) -> tuple[bool, str]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False, f"unknown cron job: {job_id}"
        self._execute_job(job_id=job_id, scheduled_for=_now_utc(), manual=True)
        with self._lock:
            updated = self._jobs.get(job_id)
        if updated is None:
            return True, f"cron job triggered: {job_id}"
        if updated.last_status == "error":
            detail = updated.last_error or "unknown error"
            return False, f"cron job failed: {job_id}\nerror: {detail}"
        preview = (updated.last_result_preview or "").strip()
        if preview:
            return True, f"cron job triggered: {job_id}\npreview: {preview}"
        return True, f"cron job triggered: {job_id}"

    def add_dynamic_job(self, job_id: str, message: str, delay_minutes: int, channel: str = "", sender_id: str = "") -> None:
        from datetime import timedelta
        fire_at = _now_utc() + timedelta(minutes=delay_minutes)
        job = CronJobState(
            job_id=job_id,
            name=f"Reminder: {message[:30]}",
            enabled=True,
            expr="",
            tz_name="UTC",
            payload_kind="agent_turn",
            message=f"[Reminder] {message}",
            agent_id="",
            delete_after_run=True,
            raw={},
            channel=channel,
            sender_id=sender_id,
        )
        job._next_run_dt = fire_at
        job.next_run_at = fire_at.isoformat()
        with self._lock:
            self._jobs[job_id] = job
        self.on_event(f"reminder set: {job_id} in {delay_minutes}m")

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.poll_seconds):
            try:
                self.reload_jobs()
                self._run_due_jobs()
            except Exception as exc:
                self.on_event(f"scheduler loop error: {exc}")

    def _run_due_jobs(self) -> None:
        now = _now_utc()
        due: list[tuple[str, datetime]] = []
        with self._lock:
            for job in self._jobs.values():
                if not job.enabled or job._next_run_dt is None:
                    continue
                if now >= job._next_run_dt:
                    scheduled_for = job._next_run_dt
                    job._next_run_dt = self._compute_next_run(job, scheduled_for)
                    job.next_run_at = job._next_run_dt.isoformat() if job._next_run_dt else ""
                    due.append((job.job_id, scheduled_for))
        for job_id, scheduled_for in due:
            self._execute_job(job_id=job_id, scheduled_for=scheduled_for, manual=False)

    def _execute_job(self, job_id: str, scheduled_for: datetime, manual: bool) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            agent_id = job.agent_id or self.agent_registry.default_agent_id
            message = job.message
            payload_kind = job.payload_kind
            delete_after_run = job.delete_after_run
            job_name = job.name
            job_channel = job.channel
            job_sender_id = job.sender_id
        if payload_kind not in {"agent_turn", "dream_run", "dream_maintain"}:
            self._mark_result(
                job_id,
                status="error",
                error=f"unsupported payload kind: {payload_kind}",
                preview="",
            )
            return
        is_reminder = job_channel and job_sender_id and message.startswith("[Reminder]")
        if is_reminder:
            reminder_text = message.replace("[Reminder]", "", 1).strip()
            self.on_event(f"delivering reminder ({job_id}) at {scheduled_for.isoformat()}")
            try:
                if self.channel_sender:
                    self.channel_sender(job_channel, job_sender_id, f"⏰ 提醒：{reminder_text}")
                    self._mark_result(job_id, status="ok", error="", preview=reminder_text[:120])
                    self.on_event(f"reminder {job_id} delivered to {job_channel}/{job_sender_id}")
                else:
                    self.on_event(f"reminder {job_id}: {reminder_text}")
                    self._mark_result(job_id, status="ok", error="", preview=reminder_text[:120])
            except Exception as exc:
                self._mark_result(job_id, status="error", error=str(exc), preview="")
                self.on_event(f"reminder {job_id} delivery failed: {exc}")
            if delete_after_run and not manual:
                self._remove_job_from_file(job_id)
                with self._lock:
                    self._jobs.pop(job_id, None)
                self.on_event(f"job {job_id} removed after run")
            return
        if payload_kind == "dream_run":
            payload = job.raw.get("payload") or {}
            plan_id = str(payload.get("plan_id") or "").strip()
            dream_agent_id = str(payload.get("agent_id") or agent_id).strip() or agent_id
            dream_channel = str(payload.get("channel") or "").strip()
            dream_user_id = str(payload.get("user_id") or "").strip()
            target_date = str(payload.get("target_date") or "").strip()
            if self.dream_service is None:
                self._mark_result(job_id, status="error", error="dream service unavailable", preview="")
                return
            try:
                result = self.dream_service.run_once(
                    plan_id=plan_id,
                    agent_id=dream_agent_id,
                    channel=dream_channel,
                    user_id=dream_user_id,
                    target_date=target_date,
                )
                preview = f"dream ok memories={result.get('new_memory_count', 0)} lessons={result.get('new_lesson_count', 0)}"
                self._mark_result(job_id, status="ok", error="", preview=preview[:120])
                self.on_event(f"job {job_id} completed")
                if delete_after_run and not manual:
                    self._remove_job_from_file(job_id)
                    with self._lock:
                        self._jobs.pop(job_id, None)
                    self.on_event(f"job {job_id} removed after run")
            except Exception as exc:
                self._mark_result(job_id, status="error", error=str(exc), preview="")
                retry_count = max(0, int(payload.get("retry_count") or 0)) + 1
                retry_at = None
                if self.dream_service is not None:
                    retry_at = self.dream_service.next_retry_time(
                        scheduled_for=scheduled_for,
                        tz_name=str((job.raw.get("schedule") or {}).get("tz") or "Local"),
                        retry_count=retry_count,
                    )
                if retry_at is not None:
                    self._reschedule_job_file(job, retry_at=retry_at, retry_count=retry_count)
                    self.reload_jobs()
                    self.on_event(f"job {job_id} failed: {exc}; retry scheduled at {retry_at.isoformat()}")
                else:
                    if delete_after_run and not manual:
                        self._remove_job_from_file(job_id)
                        with self._lock:
                            self._jobs.pop(job_id, None)
                    self.on_event(f"job {job_id} failed: {exc}")
            return
        if payload_kind == "dream_maintain":
            if self.dream_service is None:
                self._mark_result(job_id, status="error", error="dream service unavailable", preview="")
                return
            try:
                summary = self.dream_service.prune_all_lessons()
                preview = (
                    f"dream maintain scopes={summary.get('scopes', 0)} "
                    f"decayed={summary.get('decayed', 0)} archived={summary.get('archived', 0)}"
                )
                self._mark_result(job_id, status="ok", error="", preview=preview[:120])
                self.on_event(f"job {job_id} completed")
            except Exception as exc:
                self._mark_result(job_id, status="error", error=str(exc), preview="")
                self.on_event(f"job {job_id} failed: {exc}")
            return
        agent = self.agent_registry.get(agent_id)
        trigger_label = "manual" if manual else scheduled_for.isoformat()
        self.on_event(f"running {job_name} ({job_id}) at {trigger_label}")
        try:
            result = self.turn_processor.process_turn(
                message,
                agent=agent,
                channel="cron",
                user_id=job_id,
                context_channel=job_channel,
                context_user_id=job_sender_id,
            )
            preview = (result.assistant_text or "").strip().replace("\n", " ")
            if len(preview) > 120:
                preview = preview[:117] + "..."
            if result.errors:
                self._mark_result(job_id, status="error", error="; ".join(result.errors), preview=preview)
                self.on_event(f"job {job_id} finished with errors")
                return
            self._mark_result(job_id, status="ok", error="", preview=preview)
            self.on_event(f"job {job_id} completed")
            if not manual and job_channel and job_sender_id and self.channel_sender:
                try:
                    reply_text = (result.assistant_text or "").strip()
                    if reply_text:
                        self.channel_sender(job_channel, job_sender_id, reply_text)
                except Exception as exc:
                    self.on_event(f"failed to route result to {job_channel}/{job_sender_id}: {exc}")
            if delete_after_run and not manual:
                self._remove_job_from_file(job_id)
                with self._lock:
                    self._jobs.pop(job_id, None)
                self.on_event(f"job {job_id} removed after run")
        except Exception as exc:
            self._mark_result(job_id, status="error", error=str(exc), preview="")
            self.on_event(f"job {job_id} failed: {exc}")

    def _mark_result(self, job_id: str, status: str, error: str, preview: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.last_run_at = _now_utc().isoformat()
            job.last_status = status
            job.last_error = error
            job.last_result_preview = preview
            last_run_at = job.last_run_at
        self._save_job_state(job_id, status, error, preview, last_run_at)

    def _build_job_state(self, raw: dict) -> CronJobState:
        schedule = raw.get("schedule") or {}
        payload = raw.get("payload") or {}
        return CronJobState(
            job_id=str(raw.get("id") or "").strip(),
            name=str(raw.get("name") or raw.get("id") or "unnamed-job"),
            enabled=bool(raw.get("enabled", True)),
            expr=str(schedule.get("expr") or "").strip(),
            tz_name=str(schedule.get("tz") or "Local").strip() or "Local",
            payload_kind=str(payload.get("kind") or "").strip(),
            message=str(payload.get("message") or "").strip(),
            agent_id=str(payload.get("agent_id") or "").strip(),
            delete_after_run=bool(raw.get("delete_after_run", False)),
            raw=raw,
            channel=str(raw.get("channel") or payload.get("channel") or "").strip(),
            sender_id=str(raw.get("sender_id") or payload.get("sender_id") or "").strip(),
        )

    def _compute_next_run(self, job: CronJobState, base_utc: datetime) -> datetime | None:
        if not job.enabled or not job.expr:
            return None
        tz = self._resolve_tz(job.tz_name)
        base_local = base_utc.astimezone(tz)
        itr = croniter(job.expr, base_local)
        next_local = itr.get_next(datetime)
        if next_local.tzinfo is None:
            next_local = next_local.replace(tzinfo=tz)
        return next_local.astimezone(timezone.utc)

    def _resolve_tz(self, tz_name: str):
        if not tz_name or tz_name.lower() == "local":
            return datetime.now().astimezone().tzinfo or timezone.utc
        try:
            return ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            return timezone.utc

    def _save_job_state(self, job_id: str, status: str, error: str, preview: str, last_run_at: str) -> None:
        try:
            data: dict[str, dict] = {}
            if self.state_file.is_file():
                try:
                    data = json.loads(self.state_file.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            data[job_id] = {
                "last_run_at": last_run_at,
                "last_status": status,
                "last_error": error,
                "last_result_preview": preview,
            }
            self.state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            self.on_event(f"failed to save cron state for {job_id}: {exc}")

    def _load_job_state(self, job_id: str) -> dict | None:
        if not self.state_file.is_file():
            return None
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return data.get(job_id)
        except Exception:
            return None

    def _read_jobs_file(self) -> list[dict]:
        if not self.cron_file.is_file():
            return []
        try:
            data = json.loads(self.cron_file.read_text(encoding="utf-8"))
        except Exception as exc:
            self.on_event(f"failed to read CRON.json: {exc}")
            return []
        jobs = data.get("jobs")
        return jobs if isinstance(jobs, list) else []

    def _reschedule_job_file(self, job: CronJobState, *, retry_at: datetime, retry_count: int) -> None:
        if not self.cron_file.is_file():
            return
        try:
            data = json.loads(self.cron_file.read_text(encoding="utf-8"))
        except Exception:
            return
        jobs = data.get("jobs")
        if not isinstance(jobs, list):
            return
        updated_jobs: list[dict] = []
        for raw in jobs:
            if not isinstance(raw, dict):
                updated_jobs.append(raw)
                continue
            if str(raw.get("id") or "") != job.job_id:
                updated_jobs.append(raw)
                continue
            rewritten = copy.deepcopy(raw)
            schedule = rewritten.get("schedule") or {}
            payload = rewritten.get("payload") or {}
            retry_local = retry_at.astimezone(self._resolve_tz(str(schedule.get("tz") or "Local")))
            schedule["expr"] = f"{retry_local.minute} {retry_local.hour} {retry_local.day} {retry_local.month} *"
            payload["retry_count"] = retry_count
            rewritten["schedule"] = schedule
            rewritten["payload"] = payload
            updated_jobs.append(rewritten)
        data["jobs"] = updated_jobs
        self.cron_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _remove_job_from_file(self, job_id: str) -> None:
        if not self.cron_file.is_file():
            return
        try:
            data = json.loads(self.cron_file.read_text(encoding="utf-8"))
        except Exception:
            return
        jobs = data.get("jobs", [])
        data["jobs"] = [j for j in jobs if j.get("id") != job_id]
        self.cron_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Also clean up state file entry
        if self.state_file.is_file():
            try:
                state_data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if job_id in state_data:
                    del state_data[job_id]
                    self.state_file.write_text(json.dumps(state_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            except Exception:
                pass
