from dataclasses import dataclass

from anthropic import Anthropic

from trustworthy_assistant.bookkeeping import BookkeepingService
from trustworthy_assistant.bootstrap import BootstrapLoader
from trustworthy_assistant.config import AppConfig, load_config
from trustworthy_assistant.eval.benchmarks import BenchmarkSuite
from trustworthy_assistant.memory.dream_service import DreamService
from trustworthy_assistant.memory.service import TrustworthyMemoryService
from trustworthy_assistant.prompting import PromptBuilder
from trustworthy_assistant.runtime.agents import AgentRegistry
from trustworthy_assistant.runtime.cron import CronScheduler
from trustworthy_assistant.runtime.maintenance import MaintenanceService
from trustworthy_assistant.runtime.sessions import SessionManager
from trustworthy_assistant.runtime.turns import TurnProcessor
from trustworthy_assistant.skills import SkillsCatalog
from trustworthy_assistant.supervisor.workflow import SupervisorWorkflow
from trustworthy_assistant.tools import ToolRegistry


@dataclass(slots=True)
class TrustworthyAssistantApp:
    config: AppConfig
    bootstrap_loader: BootstrapLoader
    skills_catalog: SkillsCatalog
    memory_service: TrustworthyMemoryService
    bookkeeping_service: BookkeepingService
    prompt_builder: PromptBuilder
    agent_registry: AgentRegistry
    session_manager: SessionManager
    maintenance_service: MaintenanceService
    benchmark_suite: BenchmarkSuite
    dream_service: DreamService
    turn_processor: TurnProcessor
    tools: ToolRegistry
    client: Anthropic
    supervisor_workflow: SupervisorWorkflow
    cron_scheduler: CronScheduler


def build_app(root_dir=None, on_tool=None, on_cron_event=None, channel_sender=None) -> TrustworthyAssistantApp:
    config = load_config(root_dir)
    memory_service = TrustworthyMemoryService(
        config.workspace_dir,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        embedding_model=config.embedding_model,
        chroma_persist_dir=config.chroma_persist_dir
    )
    bookkeeping_service = BookkeepingService(config.workspace_dir)
    config.benchmark_dir.mkdir(parents=True, exist_ok=True)
    agent_registry = AgentRegistry()
    session_manager = SessionManager()
    client = Anthropic(api_key=config.anthropic_api_key, base_url=config.anthropic_base_url)
    bootstrap_loader = BootstrapLoader(config)
    skills_catalog = SkillsCatalog(config)
    prompt_builder = PromptBuilder(config.model_id)
    maintenance_service = MaintenanceService(memory_service)
    benchmark_suite = BenchmarkSuite()
    supervisor_workflow = SupervisorWorkflow()
    dream_service = DreamService(
        workspace_dir=config.workspace_dir,
        memory_service=memory_service,
        client=client,
        model_id=config.model_id,
        enabled=config.nightly_dream_enabled,
        min_digest_count=config.nightly_dream_min_digest_count,
        min_digest_chars=config.nightly_dream_min_digest_chars,
        window_start_hour=config.nightly_dream_window_start_hour,
        window_end_hour=config.nightly_dream_window_end_hour,
        on_event=on_cron_event,
    )
    dream_service.ensure_maintenance_job()

    _reminder_state: dict = {"counter": 0}
    cron_scheduler_placeholder: list = [None]

    def _reminder_callback(message: str, delay_minutes: int, channel: str = "", sender_id: str = "") -> None:
        _reminder_state["counter"] += 1
        job_id = f"reminder-{_reminder_state['counter']}"
        cs = cron_scheduler_placeholder[0]
        if cs is not None:
            cs.add_dynamic_job(job_id, message, delay_minutes, channel=channel, sender_id=sender_id)

    tools = ToolRegistry(
        memory_service,
        bookkeeping_service=bookkeeping_service,
        on_tool=on_tool,
        reminder_callback=_reminder_callback,
        anthropic_client=client,
        anthropic_api_key=config.anthropic_api_key,
        anthropic_base_url=config.anthropic_base_url,
        model_id=config.model_id,
        vision_api_key=config.vision_api_key,
        vision_base_url=config.vision_base_url,
        vision_model_id=config.vision_model_id,
        supervisor_workflow=supervisor_workflow,
        state_dir=config.root_dir / ".trustworthy_state",
    )

    turn_processor = TurnProcessor(
        client=client,
        prompt_builder=prompt_builder,
        bootstrap_loader=bootstrap_loader,
        skills_catalog=skills_catalog,
        memory_service=memory_service,
        tool_registry=tools,
        session_manager=session_manager,
        model_id=config.model_id,
        dream_service=dream_service,
    )

    cron_scheduler = CronScheduler(
        workspace_dir=config.workspace_dir,
        agent_registry=agent_registry,
        turn_processor=turn_processor,
        dream_service=dream_service,
        on_event=on_cron_event,
    )
    cron_scheduler_placeholder[0] = cron_scheduler
    if channel_sender is not None:
        cron_scheduler.channel_sender = channel_sender
        cron_scheduler.start()

    return TrustworthyAssistantApp(
        config=config,
        bootstrap_loader=bootstrap_loader,
        skills_catalog=skills_catalog,
        memory_service=memory_service,
        bookkeeping_service=bookkeeping_service,
        prompt_builder=prompt_builder,
        agent_registry=agent_registry,
        session_manager=session_manager,
        maintenance_service=maintenance_service,
        benchmark_suite=benchmark_suite,
        dream_service=dream_service,
        turn_processor=turn_processor,
        tools=tools,
        client=client,
        supervisor_workflow=supervisor_workflow,
        cron_scheduler=cron_scheduler,
    )
