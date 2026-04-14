from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedTextBlock:
    text: str


@dataclass(frozen=True, slots=True)
class NormalizedToolCall:
    name: str
    input: dict[str, Any]
    tool_use_id: str | None = None
    result_mode: str = "tool_result"
    raw: str = ""


@dataclass(frozen=True, slots=True)
class NormalizedResponse:
    stop_reason: str
    texts: list[NormalizedTextBlock]
    tool_calls: list[NormalizedToolCall]
    raw_summary: str


def _parse_minimax_tool_call(text: str) -> list[NormalizedToolCall]:
    if "<minimax:tool_call>" not in text:
        return []
    calls: list[NormalizedToolCall] = []
    invoke_pattern = re.compile(r'<invoke\s+name="([^"]+)">(.*?)</invoke>', re.DOTALL)
    param_pattern = re.compile(r'<parameter\s+name="([^"]+)">(.*?)</parameter>', re.DOTALL)
    for match in invoke_pattern.finditer(text):
        name = match.group(1)
        body = match.group(2)
        params: dict[str, Any] = {}
        for param in param_pattern.finditer(body):
            params[param.group(1)] = param.group(2).strip()
        calls.append(
            NormalizedToolCall(
                name=name,
                input=params,
                tool_use_id=None,
                result_mode="text_feedback",
                raw=match.group(0),
            )
        )
    return calls


def _parse_bracket_tool_call(text: str) -> list[NormalizedToolCall]:
    if "[TOOL_CALL]" not in text:
        return []
    calls: list[NormalizedToolCall] = []
    block_pattern = re.compile(r"\[TOOL_CALL\](.*?)\[/TOOL_CALL\]", re.DOTALL)
    tool_pattern = re.compile(r'tool\s*=>\s*"([^"]+)"')
    args_pattern = re.compile(r"args\s*=>\s*\{(.*)\}", re.DOTALL)
    flag_pattern = re.compile(r"--([a-zA-Z0-9_-]+)\s+\"((?:\\\"|[^\"])*)\"")
    for match in block_pattern.finditer(text):
        raw = match.group(0)
        body = match.group(1)
        tool_match = tool_pattern.search(body)
        if not tool_match:
            continue
        tool_name = tool_match.group(1).strip()
        params: dict[str, Any] = {}
        args_match = args_pattern.search(body)
        if args_match:
            args_body = args_match.group(1)
            for flag_match in flag_pattern.finditer(args_body):
                params[flag_match.group(1)] = flag_match.group(2).replace('\\"', '"').strip()
        calls.append(
            NormalizedToolCall(
                name=tool_name,
                input=params,
                tool_use_id=None,
                result_mode="text_feedback",
                raw=raw,
            )
        )
    return calls


def normalize_response(response: Any) -> NormalizedResponse:
    texts: list[NormalizedTextBlock] = []
    tool_calls: list[NormalizedToolCall] = []
    block_summaries: list[str] = []
    for index, block in enumerate(getattr(response, "content", []) or []):
        block_type = getattr(block, "type", None)
        block_name = getattr(block, "name", None)
        text = getattr(block, "text", None)
        block_summaries.append(f"{index}:{block_type}:{block_name or '-'}:text={bool(text)}")
        if block_type == "tool_use":
            tool_calls.append(
                NormalizedToolCall(
                    name=getattr(block, "name", ""),
                    input=getattr(block, "input", {}) or {},
                    tool_use_id=getattr(block, "id", None),
                    result_mode="tool_result",
                    raw=repr(block),
                )
            )
            continue
        if text:
            parsed_calls = _parse_minimax_tool_call(text)
            if not parsed_calls:
                parsed_calls = _parse_bracket_tool_call(text)
            if parsed_calls:
                tool_calls.extend(parsed_calls)
                continue
            texts.append(NormalizedTextBlock(text=text))
    stop_reason = getattr(response, "stop_reason", None) or ("tool_use" if tool_calls else "end_turn")
    return NormalizedResponse(
        stop_reason=stop_reason,
        texts=texts,
        tool_calls=tool_calls,
        raw_summary=f"stop_reason={getattr(response, 'stop_reason', None)} blocks=[{', '.join(block_summaries)}]",
    )
