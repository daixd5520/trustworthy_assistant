from dataclasses import dataclass, field
import re
import time
from typing import Callable, Optional

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


@dataclass(slots=True)
class ProgressTracker:
    user_input: str
    current_phase: str = "idle"
    emitted_phases: set[str] = field(default_factory=set)
    last_note: str = ""
    emitted_count: int = 0
    max_updates: int = 2

    def _suppress_progress_updates(self) -> bool:
        text = (self.user_input or "").strip()
        return "图片" in text and "本地路径" in text

    def next_note(self, normalized, tool_roundtrips: int) -> str:
        if self._suppress_progress_updates():
            return ""
        if self.emitted_count >= self.max_updates:
            return ""
        explicit = self._compact_text("".join(block.text for block in normalized.texts).strip())
        if explicit and explicit != self.last_note:
            self.last_note = explicit
            self.emitted_count += 1
            return explicit
        if not normalized.tool_calls:
            return ""
        phase = self._infer_phase([call.name for call in normalized.tool_calls], tool_roundtrips)
        if not phase:
            return ""
        if not self._should_announce(phase):
            return ""
        note = self._compose_note(phase, tool_roundtrips=tool_roundtrips)
        if note:
            self.current_phase = phase
            self.emitted_phases.add(phase)
            self.last_note = note
            self.emitted_count += 1
        return note

    @staticmethod
    def _compact_text(text: str, limit: int = 72) -> str:
        if not text:
            return ""
        first = text.split("\n\n", 1)[0].strip()
        if len(first) <= limit:
            return first
        return first[:limit].rstrip() + "..."

    @staticmethod
    def _phase_rank(phase: str) -> int:
        return {
            "idle": 0,
            "orient": 1,
            "inspect": 2,
            "verify": 3,
            "act": 4,
        }.get(phase, 0)

    def _infer_phase(self, tool_names: list[str], tool_roundtrips: int) -> str:
        names = set(tool_names)
        if "send_file" in names:
            return "act"
        if "set_reminder" in names:
            return "act"
        if {"write_file", "append_file", "replace_in_file", "make_directory"} & names:
            return "act"
        if "run_command" in names:
            return "verify"
        if "read_file" in names:
            return "inspect"
        if "list_directory" in names or "memory_search" in names or "get_current_time" in names:
            return "orient" if tool_roundtrips == 0 else "inspect"
        return "orient" if tool_roundtrips == 0 else ""

    def _should_announce(self, phase: str) -> bool:
        if phase in self.emitted_phases:
            return False
        # Only announce when moving the task forward, not when bouncing sideways.
        return self._phase_rank(phase) > self._phase_rank(self.current_phase)

    def _subject_hint(self) -> str:
        text = (self.user_input or "").strip()
        if "图片" in text and "本地路径" in text:
            multi_match = re.search(r"发送了\s+(\d+)\s+张图片", text)
            if multi_match:
                try:
                    if int(multi_match.group(1)) > 1:
                        return "这些图片"
                except ValueError:
                    pass
            return "这张图片"
        path_match = re.search(r"(`[^`]+`|/[^\s]+|[A-Za-z0-9_./-]+\.[A-Za-z0-9]+)", text)
        if path_match:
            return path_match.group(1).strip("`")
        hint_map = [
            ("目录", "目录结构"),
            ("文件", "文件内容"),
            ("代码", "这段代码"),
            ("配置", "配置"),
            ("报错", "报错原因"),
            ("问题", "这个问题"),
            ("总结", "今天的记录"),
        ]
        for keyword, hint in hint_map:
            if keyword in text:
                return hint
        return ""

    def _compose_note(self, stage: str, tool_roundtrips: int) -> str:
        subject = self._subject_hint()
        idx = len(self.emitted_phases)
        if stage == "orient":
            options = [
                f"我先把{subject}的脉络捋一下。" if subject else "我先把来龙去脉捋一下。",
                f"我先找一下{subject}的入口。" if subject else "我先找一下入口。",
                f"我先对一下{subject}周围的上下文。" if subject else "我先对一下相关上下文。",
            ]
            return options[idx % len(options)]
        if stage == "inspect":
            options = [
                f"我先看下{subject}里具体写了什么。" if subject else "我先看下具体内容。",
                f"我先把{subject}细读一下。" if subject else "我先细看一下相关实现。",
                f"我先对一下{subject}的细节。" if subject else "我先对一下里面的细节。",
            ]
            return options[idx % len(options)]
        if stage == "verify":
            options = [
                "我先跑一下验证，看看实际情况。",
                f"我先验证一下{subject}。" if subject else "我先做个快速验证。",
                "我先看下运行结果再判断。",
            ]
            return options[idx % len(options)]
        if stage == "act":
            options = [
                "我整理一下，马上给你。",
                "我这边收个尾，马上发你。",
                "我先把结果落一下，然后给你。",
            ]
            return options[idx % len(options)]
        return ""


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

    @staticmethod
    def _should_retry_provider_error(exc: Exception) -> bool:
        message = str(exc).lower()
        retry_markers = (
            "error code 500",
            "unknown error 520",
            "internal server error",
            "server error",
            "gateway",
            "timeout",
            "timed out",
            "connection reset",
            "temporarily unavailable",
            "overloaded",
        )
        return any(marker in message for marker in retry_markers)

    def _create_message_with_retry(self, *, model: str, system_prompt: str, messages, max_attempts: int = 3):
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                return self.client.messages.create(
                    model=model,
                    max_tokens=8096,
                    system=system_prompt,
                    tools=self.tool_registry.tools,
                    messages=messages,
                )
            except Exception as exc:
                last_exc = exc
                if attempt >= max_attempts or not self._should_retry_provider_error(exc):
                    raise
                time.sleep(0.8 * attempt)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("provider request failed without exception detail")

    def _stream_message_with_retry(self, *, model: str, system_prompt: str, messages, on_text: Optional[Callable[[str], None]], max_attempts: int = 3):
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            current_text = ""
            try:
                with self.client.messages.stream(
                    model=model,
                    max_tokens=8096,
                    system=system_prompt,
                    tools=self.tool_registry.tools,
                    messages=messages,
                ) as stream:
                    for event in stream:
                        if event.type == "content_block_delta" and event.delta.type == "text_delta":
                            text = event.delta.text
                            current_text += text
                            if on_text:
                                on_text(text)
                    response = stream.get_final_message()
                return response, current_text
            except Exception as exc:
                last_exc = exc
                # Once partial output has been emitted, do not retry or we may duplicate content.
                if current_text or attempt >= max_attempts or not self._should_retry_provider_error(exc):
                    raise
                time.sleep(0.8 * attempt)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("provider stream failed without exception detail")

    def build_memory_context(self, user_message: str) -> str:
        results = self.memory_service.hybrid_search(user_message, top_k=3)
        if not results:
            return ""
        return "\n".join(
            f"- [{item['path']}] (status={item['status']}, score={item['score']}) {item['snippet']}"
            for item in results
        )

    def build_daily_digest_context(self, channel: str, user_id: str, agent_id: str) -> str:
        if channel == "cron":
            return self.memory_service.format_daily_digest_context(agent_id=agent_id)
        return self.memory_service.format_daily_digest_context(
            channel=channel,
            user_id=user_id,
            agent_id=agent_id,
        )

    def _record_turn_digest(
        self,
        *,
        user_input: str,
        assistant_text: str,
        channel: str,
        user_id: str,
        session_key: str,
        agent_id: str,
        tool_roundtrips: int,
        errors: list[str],
    ) -> None:
        try:
            self.memory_service.append_conversation_digest(
                user_input=user_input,
                assistant_text=assistant_text,
                channel=channel,
                user_id=user_id,
                session_key=session_key,
                agent_id=agent_id,
                tool_roundtrips=tool_roundtrips,
                errors=errors,
            )
        except Exception:
            pass

    def process_turn(
        self,
        user_input: str,
        agent: AgentProfile,
        channel: str = "terminal",
        user_id: str = "local",
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> TurnResult:
        session = self.session_manager.get_or_create(agent.agent_id, channel=channel, user_id=user_id)
        self.tool_registry.set_channel_context(channel, user_id, user_input, session.session_key)
        bootstrap_data = self.bootstrap_loader.load_all(mode=agent.prompt_mode)
        self.skills_catalog.discover()
        skills_block = self.skills_catalog.format_prompt_block()
        self.memory_service.ingest_user_message(user_input, session_key=session.session_key)
        memory_context = self.build_memory_context(user_input)
        daily_digest_context = self.build_daily_digest_context(channel, user_id, agent.agent_id)
        system_prompt = self.prompt_builder.build(
            bootstrap=bootstrap_data,
            skills_block=skills_block,
            registered_tools_block=self.tool_registry.format_prompt_block(),
            memory_context=memory_context,
            daily_digest_context=daily_digest_context,
            mode=agent.prompt_mode,
            agent_id=agent.agent_id,
            channel=channel,
        )
        self.session_manager.append(session.session_key, "user", user_input)
        tool_roundtrips = 0
        errors: list[str] = []
        progress_tracker = ProgressTracker(user_input)
        while True:
            try:
                response = self._create_message_with_retry(
                    model=agent.model_override or self.model_id,
                    system_prompt=system_prompt,
                    messages=session.messages,
                )
            except Exception as exc:
                errors.append(str(exc))
                result = TurnResult(
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
                self._record_turn_digest(
                    user_input=user_input,
                    assistant_text="",
                    channel=channel,
                    user_id=user_id,
                    session_key=session.session_key,
                    agent_id=agent.agent_id,
                    tool_roundtrips=tool_roundtrips,
                    errors=errors,
                )
                return result
            normalized = normalize_response(response)
            provider_trace = normalized.raw_summary
            self.session_manager.append(session.session_key, "assistant", response.content)
            if normalized.tool_calls:
                progress_text = progress_tracker.next_note(normalized, tool_roundtrips)
                if progress_text and on_progress is not None:
                    try:
                        on_progress(progress_text)
                    except Exception:
                        pass
            if normalized.stop_reason == "end_turn" and not normalized.tool_calls:
                assistant_text = "".join(block.text for block in normalized.texts)
                result = TurnResult(
                    agent_id=agent.agent_id,
                    session_key=session.session_key,
                    assistant_text=assistant_text,
                    tool_roundtrips=tool_roundtrips,
                    recalled_memory=memory_context,
                    trace=self.memory_service.format_last_trace(),
                    raw_stop_reason=normalized.stop_reason,
                    provider_trace=provider_trace,
                )
                self._record_turn_digest(
                    user_input=user_input,
                    assistant_text=assistant_text,
                    channel=channel,
                    user_id=user_id,
                    session_key=session.session_key,
                    agent_id=agent.agent_id,
                    tool_roundtrips=tool_roundtrips,
                    errors=errors,
                )
                return result
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
            result = TurnResult(
                agent_id=agent.agent_id,
                session_key=session.session_key,
                assistant_text=assistant_text,
                tool_roundtrips=tool_roundtrips,
                recalled_memory=memory_context,
                trace=self.memory_service.format_last_trace(),
                raw_stop_reason=normalized.stop_reason or "",
                provider_trace=provider_trace,
            )
            self._record_turn_digest(
                user_input=user_input,
                assistant_text=assistant_text,
                channel=channel,
                user_id=user_id,
                session_key=session.session_key,
                agent_id=agent.agent_id,
                tool_roundtrips=tool_roundtrips,
                errors=errors,
            )
            return result
    
    def process_turn_stream(self, user_input: str, agent: AgentProfile, channel: str = "terminal", 
                           user_id: str = "local", on_text: Optional[Callable[[str], None]] = None) -> TurnResult:
        session = self.session_manager.get_or_create(agent.agent_id, channel=channel, user_id=user_id)
        self.tool_registry.set_channel_context(channel, user_id, user_input, session.session_key)
        bootstrap_data = self.bootstrap_loader.load_all(mode=agent.prompt_mode)
        self.skills_catalog.discover()
        skills_block = self.skills_catalog.format_prompt_block()
        self.memory_service.ingest_user_message(user_input, session_key=session.session_key)
        memory_context = self.build_memory_context(user_input)
        daily_digest_context = self.build_daily_digest_context(channel, user_id, agent.agent_id)
        system_prompt = self.prompt_builder.build(
            bootstrap=bootstrap_data,
            skills_block=skills_block,
            registered_tools_block=self.tool_registry.format_prompt_block(),
            memory_context=memory_context,
            daily_digest_context=daily_digest_context,
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
                response, current_text = self._stream_message_with_retry(
                    model=agent.model_override or self.model_id,
                    system_prompt=system_prompt,
                    messages=session.messages,
                    on_text=on_text,
                )
                full_text += current_text
            except Exception as exc:
                errors.append(str(exc))
                result = TurnResult(
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
                self._record_turn_digest(
                    user_input=user_input,
                    assistant_text=full_text,
                    channel=channel,
                    user_id=user_id,
                    session_key=session.session_key,
                    agent_id=agent.agent_id,
                    tool_roundtrips=tool_roundtrips,
                    errors=errors,
                )
                return result
            normalized = normalize_response(response)
            provider_trace = normalized.raw_summary
            self.session_manager.append(session.session_key, "assistant", response.content)
            if normalized.stop_reason == "end_turn" and not normalized.tool_calls:
                result = TurnResult(
                    agent_id=agent.agent_id,
                    session_key=session.session_key,
                    assistant_text=full_text,
                    tool_roundtrips=tool_roundtrips,
                    recalled_memory=memory_context,
                    trace=self.memory_service.format_last_trace(),
                    raw_stop_reason=normalized.stop_reason,
                    provider_trace=provider_trace,
                )
                self._record_turn_digest(
                    user_input=user_input,
                    assistant_text=full_text,
                    channel=channel,
                    user_id=user_id,
                    session_key=session.session_key,
                    agent_id=agent.agent_id,
                    tool_roundtrips=tool_roundtrips,
                    errors=errors,
                )
                return result
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
            result = TurnResult(
                agent_id=agent.agent_id,
                session_key=session.session_key,
                assistant_text=full_text,
                tool_roundtrips=tool_roundtrips,
                recalled_memory=memory_context,
                trace=self.memory_service.format_last_trace(),
                raw_stop_reason=normalized.stop_reason or "",
                provider_trace=provider_trace,
            )
            self._record_turn_digest(
                user_input=user_input,
                assistant_text=full_text,
                channel=channel,
                user_id=user_id,
                session_key=session.session_key,
                agent_id=agent.agent_id,
                tool_roundtrips=tool_roundtrips,
                errors=errors,
            )
            return result
