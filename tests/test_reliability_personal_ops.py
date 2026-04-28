import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
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

try:
    import httpx  # type: ignore
except Exception:
    fake_httpx = ModuleType("httpx")

    class _ConnectTimeout(Exception):
        pass

    class _ReadTimeout(Exception):
        pass

    class _Client:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def post(self, *args, **kwargs):
            raise NotImplementedError()

        def get(self, *args, **kwargs):
            raise NotImplementedError()

        def close(self):
            return None

    fake_httpx.ConnectTimeout = _ConnectTimeout
    fake_httpx.ReadTimeout = _ReadTimeout
    fake_httpx.Client = _Client
    sys.modules.setdefault("httpx", fake_httpx)
    import httpx  # type: ignore

try:
    import fastapi  # type: ignore
except Exception:
    fake_fastapi = ModuleType("fastapi")

    class _FastAPI:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def on_event(self, *_args, **_kwargs):
            def _decorator(fn):
                return fn
            return _decorator

        def get(self, *_args, **_kwargs):
            def _decorator(fn):
                return fn
            return _decorator

        def post(self, *_args, **_kwargs):
            def _decorator(fn):
                return fn
            return _decorator

    class _HTTPException(Exception):
        pass

    fake_fastapi.FastAPI = _FastAPI
    fake_fastapi.Request = object
    fake_fastapi.HTTPException = _HTTPException
    fake_fastapi.BackgroundTasks = object
    sys.modules.setdefault("fastapi", fake_fastapi)

try:
    import pydantic  # type: ignore
except Exception:
    fake_pydantic = ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **kwargs) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    fake_pydantic.BaseModel = _BaseModel
    sys.modules.setdefault("pydantic", fake_pydantic)

try:
    import anthropic  # type: ignore
except Exception:
    fake_anthropic = ModuleType("anthropic")

    class _Anthropic:
        def __init__(self, *args, **kwargs) -> None:
            pass

    fake_anthropic.Anthropic = _Anthropic
    sys.modules.setdefault("anthropic", fake_anthropic)

try:
    import dotenv  # type: ignore
except Exception:
    fake_dotenv = ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda *args, **kwargs: None
    sys.modules.setdefault("dotenv", fake_dotenv)

if "croniter" not in sys.modules:
    fake_croniter = ModuleType("croniter")

    class _CronIter:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_next(self, _cls):
            raise NotImplementedError()

    fake_croniter.croniter = _CronIter
    sys.modules.setdefault("croniter", fake_croniter)

if "openai" not in sys.modules:
    fake_openai = ModuleType("openai")

    class _OpenAI:
        def __init__(self, *args, **kwargs) -> None:
            pass

    fake_openai.OpenAI = _OpenAI
    sys.modules.setdefault("openai", fake_openai)


from trustworthy_assistant.channels.wechat import ILinkWeChatClient
from trustworthy_assistant.channels.wechat import WeChatBotRunner
from trustworthy_assistant.config import AppConfig
from trustworthy_assistant.memory.service import TrustworthyMemoryService
from trustworthy_assistant.ops.service import PersonalOpsService
from trustworthy_assistant.prompting import PromptBuilder
from trustworthy_assistant.skills import SkillsCatalog
from trustworthy_assistant.slash_commands import handle_slash_command
from trustworthy_assistant.cli import handle_repl_command


def _build_memory_service(workspace_dir: Path) -> TrustworthyMemoryService:
    service = TrustworthyMemoryService(workspace_dir)
    service.vector_store.add = lambda *args, **kwargs: []  # type: ignore[method-assign]
    service.vector_store.search = lambda *args, **kwargs: []  # type: ignore[method-assign]
    return service


class _FailingHTTPClient:
    def post(self, *args, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    def close(self):
        return None


class _FakePromptBuilder:
    def build(self, **kwargs):
        return "\n".join(
            [
                f"ops={kwargs.get('ops_context', '')}",
                f"memory={kwargs.get('memory_context', '')}",
            ]
        )


class _FakeBootstrapLoader:
    def load_all(self, mode="full"):
        return {}


class _FakeSkillsCatalog:
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
    def __init__(self, ops_service):
        self.ops_service = ops_service

    def build_memory_context(self, user_message: str, *, channel: str, user_id: str, agent_id: str) -> str:
        return ""

    def build_lessons_context(self, user_message: str, *, channel: str, user_id: str, agent_id: str) -> str:
        return ""

    def build_daily_digest_context(self, channel: str, user_id: str, agent_id: str) -> str:
        return ""

    def build_ops_context(self, *, channel: str, user_id: str, agent_id: str) -> str:
        return self.ops_service.format_pending_context(agent_id=agent_id, channel=channel, user_id=user_id)


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
    def __init__(self, memory_service, ops_service):
        self.memory_service = memory_service
        self.ops_service = ops_service
        self.prompt_builder = _FakePromptBuilder()
        self.bootstrap_loader = _FakeBootstrapLoader()
        self.skills_catalog = _FakeSkillsCatalog()
        self.tools = _FakeTools()
        self.session_manager = _FakeSessionManager()
        self.turn_processor = _FakeTurnProcessor(ops_service)
        self.agent_registry = _FakeAgentRegistry()
        self.maintenance_service = _FakeMaintenanceService()
        self.supervisor_workflow = _FakeSupervisorWorkflow()
        self.cron_scheduler = _FakeCronScheduler()


class _FakeRunnerApp(_FakeApp):
    def __init__(self, memory_service, ops_service, root_dir: Path):
        super().__init__(memory_service, ops_service)
        self.config = type("Config", (), {"root_dir": root_dir})()


class ReliabilityAndOpsTests(unittest.TestCase):
    def test_skills_catalog_discovers_ops_extractor_from_dot_trae(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config = AppConfig(
            root_dir=project_root,
            workspace_dir=project_root / "workspace",
            benchmark_dir=project_root / "workspace" / "benchmarks",
            model_id="test-model",
            anthropic_api_key="",
            anthropic_base_url=None,
        )
        catalog = SkillsCatalog(config)
        catalog.discover()
        names = {skill["name"] for skill in catalog.skills}
        self.assertIn("ops-extractor", names)

    def test_wechat_get_updates_degrades_on_connect_timeout(self) -> None:
        client = ILinkWeChatClient("https://example.com/")
        client.client = _FailingHTTPClient()
        payload = client.get_updates("token-1", get_updates_buf="buf-1")
        self.assertEqual(payload["ret"], 0)
        self.assertEqual(payload["msgs"], [])
        self.assertEqual(payload["get_updates_buf"], "buf-1")
        self.assertIn("error", payload)

    def test_personal_ops_service_add_list_and_complete_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            service = PersonalOpsService(workspace_dir)
            created = service.add_commitment(
                title="跟进 Reliability Layer 设计",
                detail="检查微信通道的超时重试策略",
                agent_id="main",
                channel="wechat",
                user_id="user-a",
            )
            pending = service.list_commitments(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                status="pending",
            )
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0]["title"], "跟进 Reliability Layer 设计")
            ok, _message = service.complete_commitment(created["commitment_id"])
            self.assertTrue(ok)
            pending_after = service.list_commitments(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                status="pending",
            )
            completed = service.list_commitments(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                status="completed",
            )
            self.assertEqual(len(pending_after), 0)
            self.assertEqual(len(completed), 1)

    def test_personal_ops_service_supports_due_at_and_more_statuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            service = PersonalOpsService(workspace_dir)
            created = service.add_commitment(
                title="整理周报",
                detail="周五前完成",
                due_at="2026-05-01T18:00:00+08:00",
                agent_id="main",
                channel="wechat",
                user_id="user-a",
            )
            ok, _message = service.set_due_at(created["commitment_id"], "2026-05-02T10:00:00+08:00")
            self.assertTrue(ok)
            ok, _message = service.block_commitment(created["commitment_id"], reason="等待老板确认")
            self.assertTrue(ok)
            blocked = service.list_commitments(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                status="blocked",
            )
            self.assertEqual(len(blocked), 1)
            self.assertEqual(blocked[0]["due_at"], "2026-05-02T10:00:00+08:00")
            self.assertEqual(blocked[0]["block_reason"], "等待老板确认")

            created2 = service.add_commitment(
                title="清理旧草稿",
                due_at="2026-04-01T10:00:00+08:00",
                agent_id="main",
                channel="wechat",
                user_id="user-a",
            )
            ok, _message = service.dismiss_commitment(created2["commitment_id"], reason="用户说不用了")
            self.assertTrue(ok)
            dismissed = service.list_commitments(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                status="dismissed",
            )
            self.assertEqual(len(dismissed), 1)
            self.assertEqual(dismissed[0]["dismiss_reason"], "用户说不用了")

    def test_personal_ops_service_can_expire_overdue_commitments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            service = PersonalOpsService(workspace_dir)
            created = service.add_commitment(
                title="过期的跟进项",
                due_at="2026-04-01T10:00:00+08:00",
                agent_id="main",
                channel="wechat",
                user_id="user-a",
            )
            summary = service.expire_overdue_commitments(now_iso="2026-04-03T10:00:00+08:00")
            self.assertEqual(summary["expired"], 1)
            expired = service.list_commitments(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                status="expired",
            )
            self.assertEqual(len(expired), 1)
            self.assertEqual(expired[0]["commitment_id"], created["commitment_id"])

    def test_personal_ops_prompt_context_lists_pending_commitments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            ops_service = PersonalOpsService(workspace_dir)
            ops_service.add_commitment(
                title="今晚检查 cron 健康状态",
                detail="观察是否有失败任务",
                agent_id="main",
                channel="wechat",
                user_id="user-a",
            )
            prompt_builder = PromptBuilder("test-model")
            prompt = prompt_builder.build(
                bootstrap={},
                memory_context="",
                lessons_context="",
                daily_digest_context="",
                ops_context=ops_service.format_pending_context(
                    agent_id="main",
                    channel="wechat",
                    user_id="user-a",
                ),
                agent_id="main",
                channel="wechat",
            )
            self.assertIn("Pending Commitments", prompt)
            self.assertIn("今晚检查 cron 健康状态", prompt)

    def test_personal_ops_slash_commands_support_add_list_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            ops_service = PersonalOpsService(workspace_dir)
            app = _FakeApp(memory_service, ops_service)

            add_result = handle_slash_command(
                app,
                "/ops add 跟进 Reliability Layer",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(add_result.handled)
            self.assertIn("added", add_result.response.lower())

            list_result = handle_slash_command(
                app,
                "/ops list",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(list_result.handled)
            self.assertIn("跟进 Reliability Layer", list_result.response)

            pending = ops_service.list_commitments(agent_id="main", channel="wechat", user_id="user-a", status="pending")
            commitment_id = pending[0]["commitment_id"]
            done_result = handle_slash_command(
                app,
                f"/ops done {commitment_id}",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(done_result.handled)
            self.assertIn("completed", done_result.response.lower())

    def test_personal_ops_slash_commands_support_due_block_and_dismiss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            ops_service = PersonalOpsService(workspace_dir)
            app = _FakeApp(memory_service, ops_service)

            add_result = handle_slash_command(
                app,
                "/ops add 准备月度汇报",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(add_result.handled)
            commitment_id = ops_service.list_commitments(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                status="pending",
            )[0]["commitment_id"]

            due_result = handle_slash_command(
                app,
                f"/ops due {commitment_id} 2026-05-03T20:00:00+08:00",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(due_result.handled)
            self.assertIn("due_at", due_result.response.lower())

            block_result = handle_slash_command(
                app,
                f"/ops block {commitment_id} 等待数据源恢复",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(block_result.handled)
            self.assertIn("blocked", block_result.response.lower())

            dismiss_result = handle_slash_command(
                app,
                f"/ops dismiss {commitment_id} 用户取消",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(dismiss_result.handled)
            self.assertIn("dismissed", dismiss_result.response.lower())

    def test_personal_ops_extract_returns_candidate_without_writing_commitment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            ops_service = PersonalOpsService(workspace_dir)
            app = _FakeApp(memory_service, ops_service)
            extract_result = handle_slash_command(
                app,
                "/ops extract 明天提醒我看一下 cron 有没有失败任务",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(extract_result.handled)
            self.assertIn("candidate", extract_result.response.lower())
            self.assertIn("cron", extract_result.response.lower())
            pending = ops_service.list_commitments(
                agent_id="main",
                channel="wechat",
                user_id="user-a",
                status="pending",
            )
            self.assertEqual(len(pending), 0)

    def test_prompt_slash_includes_ops_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            ops_service = PersonalOpsService(workspace_dir)
            ops_service.add_commitment(
                title="检查待办巡检",
                agent_id="main",
                channel="wechat",
                user_id="user-a",
            )
            app = _FakeApp(memory_service, ops_service)
            result = handle_slash_command(
                app,
                "/prompt",
                channel="wechat",
                user_id="user-a",
                current_agent_id="main",
            )
            self.assertTrue(result.handled)
            self.assertIn("检查待办巡检", result.response)

    def test_cli_ops_command_supports_add_list_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            ops_service = PersonalOpsService(workspace_dir)
            app = _FakeApp(memory_service, ops_service)

            handled = handle_repl_command(app, "/ops add 跟进个人运营系统", {}, "", "main")
            self.assertTrue(handled)
            pending = ops_service.list_commitments(
                agent_id="main",
                channel="terminal",
                user_id="local",
                status="pending",
            )
            self.assertEqual(len(pending), 1)
            handled = handle_repl_command(app, "/ops done " + pending[0]["commitment_id"], {}, "", "main")
            self.assertTrue(handled)
            completed = ops_service.list_commitments(
                agent_id="main",
                channel="terminal",
                user_id="local",
                status="completed",
            )
            self.assertEqual(len(completed), 1)

    def test_wechat_runner_tracks_poll_health_when_timeout_occurs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace_dir = Path(tmp_dir) / "workspace"
            workspace_dir.mkdir(parents=True, exist_ok=True)
            memory_service = _build_memory_service(workspace_dir)
            ops_service = PersonalOpsService(workspace_dir)
            app = _FakeRunnerApp(memory_service, ops_service, workspace_dir)
            events: list[str] = []
            runner = WeChatBotRunner(app, on_event=events.append)
            payload = {
                "ret": 0,
                "msgs": [],
                "get_updates_buf": "buf-1",
                "error": "timeout",
            }
            sleep_s = runner._handle_poll_result(payload)
            self.assertGreaterEqual(sleep_s, 1.0)
            self.assertEqual(runner._poll_health["status"], "degraded")
            self.assertEqual(runner._poll_health["consecutive_failures"], 1)
            self.assertTrue(any("poll degraded" in item for item in events))


if __name__ == "__main__":
    unittest.main()
