from datetime import datetime, timezone


class PromptBuilder:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def build(
        self,
        bootstrap: dict[str, str] | None = None,
        skills_block: str = "",
        registered_tools_block: str = "",
        memory_context: str = "",
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
            if parts:
                sections.append("## Memory\n\n" + "\n\n".join(parts))
            sections.append(
                "## Memory Instructions\n\n"
                "- Use memory_write to save important user facts and preferences.\n"
                "- Reference remembered facts naturally in conversation.\n"
                "- Use memory_search to recall specific past information."
            )
        if mode in {"full", "minimal"}:
            for name in ["HEARTBEAT.md", "BOOTSTRAP.md", "AGENTS.md", "USER.md"]:
                content = bootstrap.get(name, "").strip()
                if content:
                    sections.append(f"## {name.replace('.md', '')}\n\n{content}")
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
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
        }
        sections.append(f"## Channel\n\n{hints.get(channel, f'You are responding via {channel}.')}")
        return "\n\n".join(sections)
