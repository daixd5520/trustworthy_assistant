import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class _FakeCollection:
    def __init__(self) -> None:
        self._items = {}

    def add(self, documents, metadatas=None, ids=None):
        for idx, doc in enumerate(documents):
            item_id = ids[idx]
            self._items[item_id] = {
                "document": doc,
                "metadata": (metadatas or [{}])[idx] if metadatas else {},
            }

    def query(self, query_texts, n_results=5, where=None):
        ids = list(self._items.keys())[:n_results]
        return {
            "ids": [ids],
            "documents": [[self._items[item_id]["document"] for item_id in ids]],
            "metadatas": [[self._items[item_id]["metadata"] for item_id in ids]],
            "distances": [[0.0 for _ in ids]],
        }

    def delete(self, ids):
        for item_id in ids:
            self._items.pop(item_id, None)

    def count(self):
        return len(self._items)


class _FakeChromaClient:
    def __init__(self, *args, **kwargs) -> None:
        self._collections = {}

    def get_collection(self, name, embedding_function=None):
        if name not in self._collections:
            raise KeyError(name)
        return self._collections[name]

    def create_collection(self, name, embedding_function=None):
        collection = _FakeCollection()
        self._collections[name] = collection
        return collection

    def delete_collection(self, name):
        self._collections.pop(name, None)


fake_chromadb = ModuleType("chromadb")
fake_chromadb.Client = _FakeChromaClient
fake_chromadb.PersistentClient = _FakeChromaClient
fake_embedding_module = ModuleType("chromadb.utils.embedding_functions")
fake_embedding_module.DefaultEmbeddingFunction = lambda: object()
fake_embedding_module.OpenAIEmbeddingFunction = lambda **kwargs: object()
fake_utils_module = ModuleType("chromadb.utils")
fake_utils_module.embedding_functions = fake_embedding_module
fake_chromadb.utils = fake_utils_module
sys.modules.setdefault("chromadb", fake_chromadb)
sys.modules.setdefault("chromadb.utils", fake_utils_module)
sys.modules.setdefault("chromadb.utils.embedding_functions", fake_embedding_module)


class _FakeCronIter:
    def __init__(self, expr, base_local) -> None:
        self.parts = str(expr).split()[:5]
        self.base_local = base_local

    def get_next(self, _cls):
        minute_expr, hour_expr, day_expr, month_expr = self.parts[:4]
        minute = self.base_local.minute if minute_expr == "*" else int(minute_expr)
        hour = self.base_local.hour if hour_expr == "*" else int(hour_expr)
        day = self.base_local.day if day_expr == "*" else int(day_expr)
        month = self.base_local.month if month_expr == "*" else int(month_expr)
        candidate = self.base_local.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= self.base_local:
            candidate = candidate + timedelta(days=1)
        return candidate


fake_croniter_module = ModuleType("croniter")
fake_croniter_module.croniter = _FakeCronIter
sys.modules.setdefault("croniter", fake_croniter_module)

from trustworthy_assistant.memory.dream_service import DreamService
from trustworthy_assistant.memory.dream_repository import DreamRepository
from trustworthy_assistant.memory.service import TrustworthyMemoryService
from trustworthy_assistant.runtime.cron import CronScheduler
from trustworthy_assistant.slash_commands import handle_slash_command


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.content = [_FakeBlock(text)]


class _FakeMessages:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def create(self, **kwargs):
        return _FakeResponse(json.dumps(self.payload, ensure_ascii=False))


class _FakeClient:
    def __init__(self, payload: dict) -> None:
        self.messages = _FakeMessages(payload)


class _FailingDreamService:
    def __init__(self, retry_at: datetime | None) -> None:
        self.retry_at = retry_at

    def run_once(self, **kwargs):
        raise RuntimeError("boom")

    def next_retry_time(self, *, scheduled_for: datetime, tz_name: str = "Local", retry_count: int = 1):
        return self.retry_at


class _DummyRegistry:
    default_agent_id = "main"

    def get(self, agent_id: str):
        return None


class _MaintainingDreamService:
    def __init__(self) -> None:
        self.called = False

    def prune_all_lessons(self):
        self.called = True
        return {"scopes": 2, "scanned": 3, "decayed": 1, "archived": 1}


class _FakePromptBuilder:
    def build(self, **kwargs):
        return "\n".join(
            [
                f"memory={kwargs.get('memory_context', '')}",
                f"lessons={kwargs.get('lessons_context', '')}",
                f"digest={kwargs.get('daily_digest_context', '')}",
                f"channel={kwargs.get('channel', '')}",
            ]
        )


class _FakeBootstrapLoader:
    def load_all(self, mode="full"):
        return {}


class _FakeSkillsCatalog:
    def __init__(self) -> None:
        self.skills = []

    def discover(self):
        return None

    def format_prompt_block(self):
        return ""


class _FakeTools:
    def format_prompt_block(self):
        return ""

    def approve_pending_command(self, session_key, remember=False):
        return "approved"

    def reject_pending_command(self, session_key):
        return "rejected"

    def format_pending_status_lines(self, session_key):
        return []


class _FakeSessionManager:
    def build_session_key(self, *, agent_id: str, channel: str, user_id: str):
        return f"{agent_id}:{channel}:{user_id}"

    def list_sessions(self):
        return []


class _FakeTurnProcessor:
    def __init__(self) -> None:
        self.memory_calls = []
        self.lesson_calls = []

    def build_memory_context(self, user_message: str, *, channel: str, user_id: str, agent_id: str) -> str:
        self.memory_calls.append((user_message, channel, user_id, agent_id))
        return f"memory::{agent_id}::{channel}::{user_id}"

    def build_lessons_context(self, user_message: str, *, channel: str, user_id: str, agent_id: str) -> str:
        self.lesson_calls.append((user_message, channel, user_id, agent_id))
        return f"lessons::{agent_id}::{channel}::{user_id}"

    def build_daily_digest_context(self, channel: str, user_id: str, agent_id: str) -> str:
        return f"digest::{agent_id}::{channel}::{user_id}"


class _FakeAgentRegistry:
    default_agent_id = "main"

    def list_profiles(self):
        return []

    def get(self, agent_id: str):
        return type("Profile", (), {"agent_id": agent_id, "name": agent_id, "personality": ""})()


class _FakeMaintenanceService:
    def run_once(self):
        return type("Report", (), {"run_at": "now", "summary": "ok", "projection_path": "/tmp/proj"})()


class _FakeSupervisorWorkflow:
    def get_current_report(self):
        return None

    def verify(self):
        return None


class _FakeCronScheduler:
    def list_jobs(self):
        return []

    def reload_jobs(self):
        return 0

    def run_job_now(self, job_id: str):
        return True, f"cron job triggered: {job_id}"


class _FakeApp:
    def __init__(self, memory_service, dream_service):
        self.memory_service = memory_service
        self.dream_service = dream_service
        self.prompt_builder = _FakePromptBuilder()
        self.bootstrap_loader = _FakeBootstrapLoader()
        self.skills_catalog = _FakeSkillsCatalog()
        self.tools = _FakeTools()
        self.session_manager = _FakeSessionManager()
        self.turn_processor = _FakeTurnProcessor()
        self.agent_registry = _FakeAgentRegistry()
        self.maintenance_service = _FakeMaintenanceService()
        self.supervisor_workflow = _FakeSupervisorWorkflow()
        self.cron_scheduler = _FakeCronScheduler()


def _build_memory_service(workspace_dir: Path) -> TrustworthyMemoryService:
    service = TrustworthyMemoryService(workspace_dir)
    service.vector_store.add = lambda *args, **kwargs: []  # type: ignore[method-assign]
    service.vector_store.search = lambda *args, **kwargs: []  # type: ignore[method-assign]
    return service


class NightlyDreamTests(unittest.TestCase):
    def test_find_plan_returns_latest_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = DreamRepository(Path(tmp_dir))
            repo.append_plan(
                {
                    "plan_id": "plan-old",
                    "agent_id": "main",
                    "channel": "wechat",
                    "user_id": "user-a",
                    "target_date": "2026-04-20",
                    "status": "failed",
                    "scheduled_for": "2026-04-21T03:00:00+08:00",
                    "created_at": "2026-04-20T21:00:00+08:00",
                }
            )
            repo.append_plan(
                {
                    "plan_id": "plan-new",
                    "agent_id": "main",
                    "channel": "wechat",
                    "user_id": "user-a",
                    "target_date": "2026-04-20",
                    "status": "scheduled",
                    "scheduled_for": "2026-04-21T04:00:00+08:00",
                    "created_at": "2026-04-20T22:00:00+08:00",
                }
            )
            selected = repo.find_plan(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                target_date="2026-04-20",
            )
            self.assertIsNotNone(selected)
            self.assertEqual(selected["plan_id"], "plan-new")

    def test_ensure_maintenance_job_writes_recurring_cron_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=None,
                model_id="test-model",
            )
            dream_service.ensure_maintenance_job()
            payload = json.loads((workspace_dir / "CRON.json").read_text(encoding="utf-8"))
            jobs = {job["id"]: job for job in payload["jobs"]}
            self.assertIn("dream-maintain-lessons", jobs)
            self.assertEqual(jobs["dream-maintain-lessons"]["payload"]["kind"], "dream_maintain")
            self.assertFalse(jobs["dream-maintain-lessons"]["delete_after_run"])

    def test_scoped_memory_search_and_dream_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=None,
                model_id="test-model",
            )

            for idx in range(3):
                memory_service.append_conversation_digest(
                    user_input=f"用户A第{idx}次讨论 nightly dream",
                    assistant_text="整理 nightly dream 的实现方案",
                    channel="wechat",
                    user_id="user-a",
                    session_key="s-a",
                    agent_id="main",
                )
            for idx in range(2):
                memory_service.append_conversation_digest(
                    user_input=f"用户B第{idx}次讨论英文回答",
                    assistant_text="优先英文回答",
                    channel="wechat",
                    user_id="user-b",
                    session_key="s-b",
                    agent_id="main",
                )

            memory_service.upsert_memory(
                "用户正在设计 nightly dream 记忆整理机制",
                category="project",
                agent_id="main",
                channel="wechat",
                user_id="user-a",
            )
            memory_service.upsert_memory(
                "用户希望优先使用英文回答。",
                category="language",
                agent_id="main",
                channel="wechat",
                user_id="user-b",
            )

            results = memory_service.hybrid_search(
                "nightly dream 设计",
                top_k=5,
                use_vector=False,
                agent_id="main",
                channel="wechat",
                user_id="user-a",
            )
            joined = "\n".join(item["snippet"] for item in results)
            self.assertIn("nightly dream", joined)
            self.assertNotIn("英文", joined)

            plan = dream_service.ensure_plan(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                local_date=memory_service.local_day_key(),
            )
            self.assertIsNotNone(plan)
            cron_payload = json.loads((workspace_dir / "CRON.json").read_text(encoding="utf-8"))
            jobs = cron_payload["jobs"]
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["payload"]["kind"], "dream_run")

    def test_dream_run_persists_report_memory_and_lessons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            fake_client = _FakeClient(
                {
                    "topics": [
                        {
                            "title": "nightly_dream",
                            "summary": "用户持续讨论 Nightly Dream 机制。",
                            "evidence_count": 3,
                            "stability": "high",
                        }
                    ],
                    "user_memories": [
                        {
                            "content": "用户在持续迭代 trustworthy_assistant 的 nightly dream 机制",
                            "category": "project",
                            "status": "candidate",
                            "confidence": 0.81,
                            "importance": 0.9,
                            "reason": "同日多次讨论并且具有持续性",
                        }
                    ],
                    "agent_lessons": [
                        {
                            "kind": "workflow",
                            "content": "讨论架构方案时优先先调研现状，再给 phased proposal。",
                            "status": "active",
                            "confidence": 0.77,
                            "importance": 0.83,
                            "reason": "用户明确要求先设计后实现",
                        }
                    ],
                    "conflicts": [],
                    "open_questions": [],
                }
            )
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=fake_client,
                model_id="test-model",
            )

            for idx in range(3):
                memory_service.append_conversation_digest(
                    user_input=f"讨论 nightly dream 第{idx}轮",
                    assistant_text="先设计，再实现",
                    channel="wechat",
                    user_id="user-a",
                    session_key="s-a",
                    agent_id="main",
                )

            plan = dream_service.ensure_plan(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                local_date=memory_service.local_day_key(),
            )
            self.assertIsNotNone(plan)

            run = dream_service.run_once(
                plan_id=plan["plan_id"],
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                target_date=memory_service.local_day_key(),
            )
            self.assertEqual(run["status"], "ok")
            self.assertTrue(Path(run["report_path"]).is_file())

            memories = memory_service.list_memories(agent_id="main", channel="wechat", user_id="user-a", limit=10)
            self.assertTrue(any("nightly dream" in row["summary"].lower() for row in memories))

            lessons = dream_service.list_lessons(limit=10)
            self.assertTrue(any("phased proposal" in str(row.get("value", "")).lower() for row in lessons))

    def test_manual_run_can_fetch_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            fake_client = _FakeClient(
                {
                    "topics": [{"title": "manual_run", "summary": "手动触发整理", "evidence_count": 3, "stability": "high"}],
                    "user_memories": [],
                    "agent_lessons": [],
                    "conflicts": [],
                    "open_questions": [],
                }
            )
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=fake_client,
                model_id="test-model",
            )
            for idx in range(3):
                memory_service.append_conversation_digest(
                    user_input=f"手动 dream 第{idx}轮",
                    assistant_text="可手动触发",
                    channel="terminal",
                    user_id="local",
                    session_key="s-local",
                    agent_id="main",
                )
            result = dream_service.run_manual(
                agent_id="main",
                channel="terminal",
                user_id="local",
                target_date="today",
            )
            self.assertEqual(result["status"], "ok")
            report = dream_service.get_report(
                agent_id="main",
                channel="terminal",
                user_id="local",
                target_date="today",
            )
            self.assertIsNotNone(report)
            self.assertIn("Nightly Dream Report", report["content"])

    def test_get_report_without_date_returns_latest_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=None,
                model_id="test-model",
            )
            scope_key = dream_service._scope_key("main", "terminal", "local")
            report_old = dream_service.repository.write_report(
                target_date="2026-04-20",
                scope_key=scope_key,
                content="# Nightly Dream Report\n\nold\n",
            )
            report_new = dream_service.repository.write_report(
                target_date="2026-04-21",
                scope_key=scope_key,
                content="# Nightly Dream Report\n\nnew\n",
            )
            dream_service.repository.append_run(
                {
                    "run_id": "run-old",
                    "plan_id": "plan-old",
                    "agent_id": "main",
                    "channel": "terminal",
                    "user_id": "local",
                    "target_date": "2026-04-20",
                    "started_at": "2026-04-21T03:00:00+08:00",
                    "finished_at": "2026-04-21T03:10:00+08:00",
                    "status": "ok",
                    "report_path": report_old,
                    "new_memory_count": 0,
                    "new_lesson_count": 0,
                    "error": "",
                }
            )
            dream_service.repository.append_run(
                {
                    "run_id": "run-new",
                    "plan_id": "plan-new",
                    "agent_id": "main",
                    "channel": "terminal",
                    "user_id": "local",
                    "target_date": "2026-04-21",
                    "started_at": "2026-04-22T03:00:00+08:00",
                    "finished_at": "2026-04-22T03:10:00+08:00",
                    "status": "ok",
                    "report_path": report_new,
                    "new_memory_count": 0,
                    "new_lesson_count": 0,
                    "error": "",
                }
            )
            latest = dream_service.get_report(agent_id="main", channel="terminal", user_id="local")
            self.assertIsNotNone(latest)
            self.assertEqual(latest["target_date"], "2026-04-21")
            self.assertIn("new", latest["content"])

    def test_similar_lessons_merge_into_single_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            fake_client = _FakeClient(
                {
                    "topics": [],
                    "user_memories": [],
                    "agent_lessons": [
                        {
                            "kind": "workflow",
                            "content": "讨论架构方案时先调研现状，再给 phased proposal。",
                            "status": "active",
                            "confidence": 0.77,
                            "importance": 0.83,
                        }
                    ],
                    "conflicts": [],
                    "open_questions": [],
                }
            )
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=fake_client,
                model_id="test-model",
            )
            synthesis = {
                "topics": [],
                "user_memories": [],
                "agent_lessons": [
                    {
                        "kind": "workflow",
                        "content": "讨论架构方案时优先先调研现状，然后给 phased proposal。",
                        "status": "active",
                        "confidence": 0.8,
                        "importance": 0.85,
                    },
                    {
                        "kind": "workflow",
                        "content": "讨论架构方案时先调研现状，再给 phased proposal。",
                        "status": "active",
                        "confidence": 0.79,
                        "importance": 0.84,
                    },
                ],
                "conflicts": [],
                "open_questions": [],
            }
            dream_service.persist_result(
                agent_id="main",
                channel="terminal",
                user_id="local",
                target_date=memory_service.local_day_key(),
                synthesis=synthesis,
            )
            lessons = dream_service.list_lessons(limit=10)
            self.assertEqual(len(lessons), 1)

    def test_dream_run_skips_sensitive_and_forces_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            fake_client = _FakeClient(
                {
                    "topics": [],
                    "user_memories": [
                        {
                            "content": "用户的银行卡号是 6222020202020202020",
                            "category": "project",
                            "status": "confirmed",
                            "confidence": 0.95,
                            "importance": 0.95,
                        },
                        {
                            "content": "用户在持续推进 nightly dream 方案",
                            "category": "project",
                            "status": "confirmed",
                            "confidence": 0.93,
                            "importance": 0.94,
                        },
                    ],
                    "agent_lessons": [],
                    "conflicts": [],
                    "open_questions": [],
                }
            )
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=fake_client,
                model_id="test-model",
            )
            for idx in range(3):
                memory_service.append_conversation_digest(
                    user_input=f"讨论 nightly dream 第{idx}轮",
                    assistant_text="先设计，再实现",
                    channel="wechat",
                    user_id="user-a",
                    session_key="s-a",
                    agent_id="main",
                )
            plan = dream_service.ensure_plan(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                local_date=memory_service.local_day_key(),
            )
            self.assertIsNotNone(plan)
            dream_service.run_once(
                plan_id=plan["plan_id"],
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                target_date=memory_service.local_day_key(),
            )
            memories = memory_service.list_memories(agent_id="main", channel="wechat", user_id="user-a", limit=10)
            joined = "\n".join(f"{row['status']}|{row['summary']}" for row in memories)
            self.assertIn("candidate|用户在持续推进 nightly dream 方案", joined)
            self.assertNotIn("银行卡号", joined)

    def test_failed_dream_job_is_rescheduled_in_same_morning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir)
            retry_at = datetime(2026, 4, 21, 4, 27, 0, tzinfo=timezone.utc)
            cron_payload = {
                "jobs": [
                    {
                        "id": "dream-user-a",
                        "name": "Nightly Dream",
                        "enabled": True,
                        "schedule": {"kind": "cron", "expr": "12 4 21 4 *", "tz": "UTC"},
                        "payload": {
                            "kind": "dream_run",
                            "plan_id": "plan-1",
                            "agent_id": "main",
                            "channel": "wechat",
                            "user_id": "user-a",
                            "target_date": "2026-04-20",
                        },
                        "delete_after_run": True,
                    }
                ]
            }
            (workspace_dir / "CRON.json").write_text(json.dumps(cron_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            scheduler = CronScheduler(
                workspace_dir,
                _DummyRegistry(),
                turn_processor=None,
                dream_service=_FailingDreamService(retry_at),
            )
            scheduler.reload_jobs()
            scheduler._execute_job(
                job_id="dream-user-a",
                scheduled_for=datetime(2026, 4, 21, 4, 12, 0, tzinfo=timezone.utc),
                manual=False,
            )
            updated = json.loads((workspace_dir / "CRON.json").read_text(encoding="utf-8"))
            job = updated["jobs"][0]
            self.assertEqual(job["payload"]["retry_count"], 1)
            self.assertEqual(job["schedule"]["expr"], "27 4 21 4 *")

    def test_dream_maintain_job_runs_global_prune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir)
            cron_payload = {
                "jobs": [
                    {
                        "id": "dream-maintain-lessons",
                        "name": "Dream Lesson Maintenance",
                        "enabled": True,
                        "schedule": {"kind": "cron", "expr": "40 5 * * *", "tz": "UTC"},
                        "payload": {"kind": "dream_maintain"},
                        "delete_after_run": False,
                    }
                ]
            }
            (workspace_dir / "CRON.json").write_text(json.dumps(cron_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            service = _MaintainingDreamService()
            scheduler = CronScheduler(
                workspace_dir,
                _DummyRegistry(),
                turn_processor=None,
                dream_service=service,
            )
            scheduler.reload_jobs()
            scheduler._execute_job(
                job_id="dream-maintain-lessons",
                scheduled_for=datetime(2026, 4, 21, 5, 40, 0, tzinfo=timezone.utc),
                manual=False,
            )
            self.assertTrue(service.called)
            jobs = scheduler.list_jobs()
            self.assertEqual(jobs[0]["last_status"], "ok")

    def test_slash_prompt_uses_scoped_memory_and_lessons_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=None,
                model_id="test-model",
            )
            app = _FakeApp(memory_service, dream_service)
            result = handle_slash_command(
                app,
                "/prompt",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(result.handled)
            self.assertIn("memory::main::wechat::user-a", result.response)
            self.assertIn("lessons::main::wechat::user-a", result.response)
            self.assertEqual(len(app.turn_processor.memory_calls), 1)
            self.assertEqual(len(app.turn_processor.lesson_calls), 1)

    def test_slash_search_and_dream_latest_are_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=None,
                model_id="test-model",
            )
            memory_service.upsert_memory(
                "用户A在推进 nightly dream 功能",
                category="project",
                agent_id="main",
                channel="wechat",
                user_id="user-a",
            )
            memory_service.upsert_memory(
                "用户B更喜欢英文回答",
                category="language",
                agent_id="main",
                channel="wechat",
                user_id="user-b",
            )
            scope_key = dream_service._scope_key("main", "wechat", "user-a")
            report_path = dream_service.repository.write_report(
                target_date="2026-04-21",
                scope_key=scope_key,
                content="# Nightly Dream Report\n\nwechat user-a latest\n",
            )
            dream_service.repository.append_run(
                {
                    "run_id": "run-wechat-a",
                    "plan_id": "plan-wechat-a",
                    "agent_id": "main",
                    "channel": "wechat",
                    "user_id": "user-a",
                    "target_date": "2026-04-21",
                    "started_at": "2026-04-22T03:00:00+08:00",
                    "finished_at": "2026-04-22T03:10:00+08:00",
                    "status": "ok",
                    "report_path": report_path,
                    "new_memory_count": 1,
                    "new_lesson_count": 0,
                    "error": "",
                }
            )
            app = _FakeApp(memory_service, dream_service)
            search_result = handle_slash_command(
                app,
                "/search nightly dream",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(search_result.handled)
            self.assertIn("nightly dream", search_result.response.lower())
            self.assertNotIn("英文回答", search_result.response)
            latest_result = handle_slash_command(
                app,
                "/dream latest",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(latest_result.handled)
            self.assertIn("wechat user-a latest", latest_result.response)

    def test_prune_lessons_decays_and_archives_old_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            dream_service = DreamService(
                workspace_dir=workspace_dir,
                memory_service=memory_service,
                client=None,
                model_id="test-model",
            )
            now = datetime.now().astimezone()
            dream_service.repository.append_lesson(
                {
                    "lesson_id": "lesson-recent-old",
                    "agent_id": "main",
                    "channel": "terminal",
                    "user_id": "local",
                    "scope": "workflow",
                    "status": "active",
                    "summary": "old active lesson",
                    "value": "Discuss architecture after surveying the current state.",
                    "confidence": 0.8,
                    "importance": 0.9,
                    "evidence_refs": [],
                    "first_seen_at": (now - timedelta(days=40)).isoformat(),
                    "last_seen_at": (now - timedelta(days=40)).isoformat(),
                    "fingerprint": "fp-1",
                }
            )
            dream_service.repository.append_lesson(
                {
                    "lesson_id": "lesson-archive-old",
                    "agent_id": "main",
                    "channel": "terminal",
                    "user_id": "local",
                    "scope": "workflow",
                    "status": "active",
                    "summary": "very old lesson",
                    "value": "Use phased proposal after research.",
                    "confidence": 0.7,
                    "importance": 0.8,
                    "evidence_refs": [],
                    "first_seen_at": (now - timedelta(days=120)).isoformat(),
                    "last_seen_at": (now - timedelta(days=120)).isoformat(),
                    "fingerprint": "fp-2",
                }
            )
            summary = dream_service.prune_lessons(
                agent_id="main",
                channel="terminal",
                user_id="local",
                stale_days=30,
                archive_days=90,
                decay_factor=0.9,
            )
            self.assertEqual(summary["scanned"], 2)
            self.assertEqual(summary["decayed"], 1)
            self.assertEqual(summary["archived"], 1)
            active_lessons = dream_service.repository.load_lessons(
                agent_id="main",
                channel="terminal",
                user_id="local",
                status="active",
                limit=10,
            )
            archived_lessons = dream_service.repository.load_lessons(
                agent_id="main",
                channel="terminal",
                user_id="local",
                status="archived",
                limit=10,
            )
            self.assertEqual(len(active_lessons), 1)
            self.assertLess(float(active_lessons[0]["importance"]), 0.9)
            self.assertEqual(len(archived_lessons), 1)


if __name__ == "__main__":
    unittest.main()
