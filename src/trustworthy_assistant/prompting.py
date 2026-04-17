from datetime import datetime


class PromptBuilder:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def build(
        self,
        bootstrap: dict[str, str] | None = None,
        skills_block: str = "",
        registered_tools_block: str = "",
        memory_context: str = "",
        daily_digest_context: str = "",
        mode: str = "full",
        agent_id: str = "main",
        channel: str = "terminal",
    ) -> str:
        bootstrap = bootstrap or {}
        sections: list[str] = []
        identity = bootstrap.get("IDENTITY.md", "").strip()
        sections.append(identity if identity else "You are a helpful personal AI assistant.")
        if mode == "full":
            soul = bootstrap.get("SOUL.md", "").strip()
            if soul:
                sections.append(f"## Personality\n\n{soul}")
        tools_md = bootstrap.get("TOOLS.md", "").strip()
        if tools_md:
            sections.append(f"## Tool Usage Guidelines\n\n{tools_md}")
        if registered_tools_block:
            sections.append(registered_tools_block)
        if mode == "full" and skills_block:
            sections.append(skills_block)
        if mode == "full":
            memory_md = bootstrap.get("MEMORY.md", "").strip()
            parts: list[str] = []
            if memory_md:
                parts.append(f"### Evergreen Memory\n\n{memory_md}")
            if memory_context:
                parts.append(f"### Recalled Memories\n\n{memory_context}")
            if daily_digest_context:
                parts.append(f"### Today's Digest\n\n{daily_digest_context}")
            if parts:
                sections.append("## Memory\n\n" + "\n\n".join(parts))
            sections.append(
                "## Memory Instructions\n\n"
                "- Use memory_write to save important user facts and preferences.\n"
                "- Reference remembered facts naturally in conversation.\n"
                "- Use memory_search to recall specific past information.\n"
                "- Use Today's Digest as the primary source for same-day summaries across restarts."
            )
        sections.append(
            "## Interaction Style\n\n"
            "- If a task needs checking, reading, searching, or tool use, first send a short natural progress note before acting.\n"
            "- Prefer short conversational updates over one monolithic message on chat-like channels.\n"
            "- Keep progress notes brief, human, and non-repetitive.\n"
            "- When you read a file, default to giving an evaluation first: summarize what the file is for, the key conclusions, quality, risks, and suggested changes.\n"
            "- Do not dump or closely paraphrase the file contents by default after using `read_file`.\n"
            "- Only show the file's raw content, long excerpts, or line-by-line details when the user explicitly asks for the content itself.\n"
            "- Prefer `write_file`, `append_file`, `replace_in_file`, and `make_directory` for filesystem edits instead of shell redirects or inline scripting."
        )
        if mode in {"full", "minimal"}:
            for name in ["HEARTBEAT.md", "BOOTSTRAP.md", "AGENTS.md", "USER.md"]:
                content = bootstrap.get(name, "").strip()
                if content:
                    sections.append(f"## {name.replace('.md', '')}\n\n{content}")
        now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
        sections.append(
            "## Runtime Context\n\n"
            f"- Agent ID: {agent_id}\n"
            f"- Model: {self.model_id}\n"
            f"- Channel: {channel}\n"
            f"- Current time: {now}\n"
            f"- Prompt mode: {mode}"
        )
        hints = {
            "terminal": "You are responding via a terminal REPL. Markdown is supported.",
            "telegram": "You are responding via Telegram. Keep messages concise.",
            "discord": "You are responding via Discord. Keep messages under 2000 characters.",
            "slack": "You are responding via Slack. Use Slack mrkdwn formatting.",
            "wechat": (
                "You are responding via WeChat. Talk like a real person chatting in short natural sentences. "
                "Prefer 1-3 short paragraphs over one dense block. "
                "Avoid sounding like a report, OCR dump, or customer service script. "
                "For image replies, first say what you see, then add one natural follow-up observation if useful."
            ),
        }
        sections.append(f"## Channel\n\n{hints.get(channel, f'You are responding via {channel}.')}")
        return "\n\n".join(sections)
