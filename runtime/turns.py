from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Generator

from trustworthy_assistant.providers.normalization import normalize_response
from trustworthy_assistant.runtime.agents import AgentProfile
from trustworthy_assistant.runtime.sessions import SessionManager


@dataclass(slots=True)
class TurnResult:
    agent_id: str
    session_key: str
    assistant_text: str
    tool_roundtrips: int
    recalled_memory: str
    trace: str = ""
    raw_stop_reason: str = ""
    provider_trace: str = ""
    errors: list[str] = field(default_factory=list)


class TurnProcessor:
    def __init__(
        self,
        client,
        prompt_builder,
        bootstrap_loader,
        skills_catalog,
        memory_service,
        tool_registry,
        session_manager: SessionManager,
        model_id: str,
    ) -> None:
        self.client = client
        self.prompt_builder = prompt_builder
        self.bootstrap_loader = bootstrap_loader
        self.skills_catalog = skills_catalog
        self.memory_service = memory_service
        self.tool_registry = tool_registry
        self.session_manager = session_manager
        self.model_id = model_id

    def build_memory_context(self, user_message: str) -> str:
        results = self.memory_service.hybrid_search(user_message, top_k=3)
        if not results:
            return ""
        return "\n".join(
            f"- [{item['path']}] (status={item['status']}, score={item['score']}) {item['snippet']}"
            for item in results
        )

    def process_turn(self, user_input: str, agent: AgentProfile, channel: str = "terminal", user_id: str = "local") -> TurnResult:
        bootstrap_data = self.bootstrap_loader.load_all(mode=agent.prompt_mode)
        self.skills_catalog.discover()
        skills_block = self.skills_catalog.format_prompt_block()
        session = self.session_manager.get_or_create(agent.agent_id, channel=channel, user_id=user_id)
        self.memory_service.ingest_user_message(user_input, session_key=session.session_key)
        memory_context = self.build_memory_context(user_input)
        system_prompt = self.prompt_builder.build(
            bootstrap=bootstrap_data,
            skills_block=skills_block,
            registered_tools_block=self.tool_registry.format_prompt_block(),
            memory_context=memory_context,
            mode=agent.prompt_mode,
            agent_id=agent.agent_id,
            channel=channel,
        )
        self.session_manager.append(session.session_key, "user", user_input)
        tool_roundtrips = 0
        errors: list[str] = []
        while True:
            try:
                response = self.client.messages.create(
                    model=agent.model_override or self.model_id,
                    max_tokens=8096,
                    system=system_prompt,
                    tools=self.tool_registry.tools,
                    messages=session.messages,
                )
            except Exception as exc:
                errors.append(str(exc))
                return TurnResult(
                    agent_id=agent.agent_id,
                    session_key=session.session_key,
                    assistant_text="",
                    tool_roundtrips=tool_roundtrips,
                    recalled_memory=memory_context,
                    trace=self.memory_service.format_last_trace(),
                    raw_stop_reason="error",
                    provider_trace="request_failed",
                    errors=errors,
                )
            normalized = normalize_response(response)
            provider_trace = normalized.raw_summary
            self.session_manager.append(session.session_key, "assistant", response.content)
            if normalized.stop_reason == "end_turn" and not normalized.tool_calls:
                assistant_text = "".join(block.text for block in normalized.texts)
                return TurnResult(
                    agent_id=agent.agent_id,
                    session_key=session.session_key,
                    assistant_text=assistant_text,
                    tool_roundtrips=tool_roundtrips,
                    recalled_memory=memory_context,
                    trace=self.memory_service.format_last_trace(),
                    raw_stop_reason=normalized.stop_reason,
                    provider_trace=provider_trace,
                )
            if normalized.tool_calls:
                tool_roundtrips += 1
                tool_results = []
                text_feedback_parts = []
                for tool_call in normalized.tool_calls:
                    result = self.tool_registry.process_tool_call(tool_call.name, tool_call.input)
                    if tool_call.result_mode == "tool_result" and tool_call.tool_use_id:
                        tool_results.append({"type": "tool_result", "tool_use_id": tool_call.tool_use_id, "content": result})
                    else:
                        text_feedback_parts.append(f"[{tool_call.name}] {result}")
                if tool_results:
                    self.session_manager.append(session.session_key, "user", tool_results)
                elif text_feedback_parts:
                    self.session_manager.append(
                        session.session_key,
                        "user",
                        "Tool execution results:\n" + "\n\n".join(text_feedback_parts),
                    )
                continue
            assistant_text = "".join(block.text for block in normalized.texts)
            return TurnResult(
                agent_id=agent.agent_id,
                session_key=session.session_key,
                assistant_text=assistant_text,
                tool_roundtrips=tool_roundtrips,
                recalled_memory=memory_context,
                trace=self.memory_service.format_last_trace(),
                raw_stop_reason=normalized.stop_reason or "",
                provider_trace=provider_trace,
            )
    
    def process_turn_stream(self, user_input: str, agent: AgentProfile, channel: str = "terminal", 
                           user_id: str = "local", on_text: Optional[Callable[[str], None]] = None) -> TurnResult:
        bootstrap_data = self.bootstrap_loader.load_all(mode=agent.prompt_mode)
        self.skills_catalog.discover()
        skills_block = self.skills_catalog.format_prompt_block()
        session = self.session_manager.get_or_create(agent.agent_id, channel=channel, user_id=user_id)
        self.memory_service.ingest_user_message(user_input, session_key=session.session_key)
        memory_context = self.build_memory_context(user_input)
        system_prompt = self.prompt_builder.build(
            bootstrap=bootstrap_data,
            skills_block=skills_block,
            registered_tools_block=self.tool_registry.format_prompt_block(),
            memory_context=memory_context,
            mode=agent.prompt_mode,
            agent_id=agent.agent_id,
            channel=channel,
        )
        self.session_manager.append(session.session_key, "user", user_input)
        tool_roundtrips = 0
        errors: list[str] = []
        full_text = ""
        
        while True:
            try:
                with self.client.messages.stream(
                    model=agent.model_override or self.model_id,
                    max_tokens=8096,
                    system=system_prompt,
                    tools=self.tool_registry.tools,
                    messages=session.messages,
                ) as stream:
                    current_text = ""
                    for event in stream:
                        if event.type == "content_block_delta" and event.delta.type == "text_delta":
                            text = event.delta.text
                            current_text += text
                            full_text += text
                            if on_text:
                                on_text(text)
                    response = stream.get_final_message()
            except Exception as exc:
                errors.append(str(exc))
                return TurnResult(
                    agent_id=agent.agent_id,
                    session_key=session.session_key,
                    assistant_text=full_text,
                    tool_roundtrips=tool_roundtrips,
                    recalled_memory=memory_context,
                    trace=self.memory_service.format_last_trace(),
                    raw_stop_reason="error",
                    provider_trace="request_failed",
                    errors=errors,
                )
            normalized = normalize_response(response)
            provider_trace = normalized.raw_summary
            self.session_manager.append(session.session_key, "assistant", response.content)
            if normalized.stop_reason == "end_turn" and not normalized.tool_calls:
                return TurnResult(
                    agent_id=agent.agent_id,
                    session_key=session.session_key,
                    assistant_text=full_text,
                    tool_roundtrips=tool_roundtrips,
                    recalled_memory=memory_context,
                    trace=self.memory_service.format_last_trace(),
                    raw_stop_reason=normalized.stop_reason,
                    provider_trace=provider_trace,
                )
            if normalized.tool_calls:
                tool_roundtrips += 1
                tool_results = []
                text_feedback_parts = []
                for tool_call in normalized.tool_calls:
                    result = self.tool_registry.process_tool_call(tool_call.name, tool_call.input)
                    if tool_call.result_mode == "tool_result" and tool_call.tool_use_id:
                        tool_results.append({"type": "tool_result", "tool_use_id": tool_call.tool_use_id, "content": result})
                    else:
                        text_feedback_parts.append(f"[{tool_call.name}] {result}")
                if tool_results:
                    self.session_manager.append(session.session_key, "user", tool_results)
                elif text_feedback_parts:
                    self.session_manager.append(
                        session.session_key,
                        "user",
                        "Tool execution results:\n" + "\n\n".join(text_feedback_parts),
                    )
                continue
            return TurnResult(
                agent_id=agent.agent_id,
                session_key=session.session_key,
                assistant_text=full_text,
                tool_roundtrips=tool_roundtrips,
                recalled_memory=memory_context,
                trace=self.memory_service.format_last_trace(),
                raw_stop_reason=normalized.stop_reason or "",
                provider_trace=provider_trace,
            )
