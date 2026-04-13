from dataclasses import dataclass

from anthropic import Anthropic

from trustworthy_assistant.bootstrap import BootstrapLoader
from trustworthy_assistant.config import AppConfig, load_config
from trustworthy_assistant.eval.benchmarks import BenchmarkSuite
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
    prompt_builder: PromptBuilder
    agent_registry: AgentRegistry
    session_manager: SessionManager
    maintenance_service: MaintenanceService
    benchmark_suite: BenchmarkSuite
    turn_processor: TurnProcessor
    tools: ToolRegistry
    client: Anthropic
    supervisor_workflow: SupervisorWorkflow
    cron_scheduler: CronScheduler


def build_app(root_dir=None, on_tool=None, on_cron_event=None) -> TrustworthyAssistantApp:
    config = load_config(root_dir)
    memory_service = TrustworthyMemoryService(
        config.workspace_dir,
        openai_api_key=config.openai_api_key,
        openai_base_url=config.openai_base_url,
        embedding_model=config.embedding_model,
        chroma_persist_dir=config.chroma_persist_dir
    )
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

    _reminder_state: dict = {"counter": 0}
    cron_scheduler_placeholder: list = [None]

    def _reminder_callback(message: str, delay_minutes: int) -> None:
        _reminder_state["counter"] += 1
        job_id = f"reminder-{_reminder_state['counter']}"
        cs = cron_scheduler_placeholder[0]
        if cs is not None:
            cs.add_dynamic_job(job_id, message, delay_minutes)

    tools = ToolRegistry(memory_service, on_tool=on_tool, reminder_callback=_reminder_callback)

    turn_processor = TurnProcessor(
        client=client,
        prompt_builder=prompt_builder,
        bootstrap_loader=bootstrap_loader,
        skills_catalog=skills_catalog,
        memory_service=memory_service,
        tool_registry=tools,
        session_manager=session_manager,
        model_id=config.model_id,
    )

    cron_scheduler = CronScheduler(
        workspace_dir=config.workspace_dir,
        agent_registry=agent_registry,
        turn_processor=turn_processor,
        on_event=on_cron_event,
    )
    cron_scheduler_placeholder[0] = cron_scheduler

    return TrustworthyAssistantApp(
        config=config,
        bootstrap_loader=bootstrap_loader,
        skills_catalog=skills_catalog,
        memory_service=memory_service,
        prompt_builder=prompt_builder,
        agent_registry=agent_registry,
        session_manager=session_manager,
        maintenance_service=maintenance_service,
        benchmark_suite=benchmark_suite,
        turn_processor=turn_processor,
        tools=tools,
        client=client,
        supervisor_workflow=supervisor_workflow,
        cron_scheduler=cron_scheduler,
    )
