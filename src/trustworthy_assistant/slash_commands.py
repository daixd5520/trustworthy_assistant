from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SlashCommandResult:
    handled: bool
    response: str = ""
    current_agent_id: str | None = None


def _render_memory_command(memory_service, arg: str) -> str:
    subparts = arg.split(maxsplit=1) if arg else []
    subcommand = subparts[0].lower() if subparts else "stats"
    subarg = subparts[1] if len(subparts) > 1 else ""
    if subcommand in {"", "stats"}:
        stats = memory_service.get_stats()
        return "\n".join(
            [
                "记忆统计",
                f"- 长期记忆 (MEMORY.md): {stats['evergreen_chars']} 字符",
                f"- 每日文件: {stats['daily_files']}",
                f"- 每日条目: {stats['daily_entries']}",
                f"- ledger 总数: {stats['ledger_total']}",
                f"- confirmed: {stats['ledger_confirmed']}  candidate: {stats['ledger_candidate']}  disputed: {stats['ledger_disputed']}",
                f"- review pending: {stats['ledger_review_pending']}",
                f"- trace 条数: {stats['trace_count']}",
                f"- projection: {stats['managed_projection_path']}",
            ]
        )
    if subcommand == "list":
        rows = memory_service.list_memories(limit=10)
        if not rows:
            return "Ledger Memories\n- (无记忆)"
        lines = ["Ledger Memories"]
        for row in rows:
            lines.append(f"- {row['memory_id']} [{row['status']}] {row['slot']}")
            lines.append(f"  {row['summary']}")
        return "\n".join(lines)
    if subcommand == "candidates":
        rows = memory_service.list_candidates(limit=10)
        if not rows:
            return "Candidate Memories\n- (无候选记忆)"
        lines = ["Candidate Memories"]
        for row in rows:
            lines.append(f"- {row['memory_id']} [{row['status']}] {row['slot']}")
            lines.append(f"  {row['summary']}")
        return "\n".join(lines)
    if subcommand == "trace":
        return "Last Retrieval Trace\n" + memory_service.format_last_trace()
    if subcommand == "conflicts":
        rows = memory_service.list_conflicts(limit=10)
        if not rows:
            return "Memory Conflicts\n- (无冲突)"
        lines = ["Memory Conflicts"]
        for row in rows:
            lines.append(f"- {row['memory_id']} [{row['status']}] {row['slot']}")
            lines.append(f"  {row['summary']}")
            lines.append(f"  conflicts_with={', '.join(row.get('conflicts_with', [])) or '-'}")
        return "\n".join(lines)
    if subcommand == "confirm":
        if not subarg:
            return "用法: /memory confirm <memory_id>"
        ok, message = memory_service.confirm_memory(subarg.strip())
        return message if ok else f"失败: {message}"
    if subcommand == "reject":
        if not subarg:
            return "用法: /memory reject <memory_id>"
        ok, message = memory_service.reject_memory(subarg.strip())
        return message if ok else f"失败: {message}"
    if subcommand == "forget":
        if not subarg:
            return "用法: /memory forget <memory_id>"
        ok, message = memory_service.forget_memory(subarg.strip())
        return message if ok else f"失败: {message}"
    if subcommand == "show":
        if not subarg:
            return "用法: /memory show <memory_id>"
        return "Memory Detail\n" + memory_service.explain_memory(subarg.strip())
    if subcommand == "sync":
        return f"Memory projection synced: {memory_service.sync_memory_markdown()}"
    return "用法: /memory [stats|list|candidates|trace|conflicts|show <id>|confirm <id>|reject <id>|forget <id>|sync]"


def handle_slash_command(
    app,
    cmd: str,
    *,
    channel: str,
    user_id: str,
    current_agent_id: str,
) -> SlashCommandResult:
    text = (cmd or "").strip()
    if not text.startswith("/"):
        return SlashCommandResult(handled=False, current_agent_id=current_agent_id)
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    session_key = app.session_manager.build_session_key(
        agent_id=current_agent_id,
        channel=channel,
        user_id=user_id,
    )

    if command == "/help":
        return SlashCommandResult(
            handled=True,
            current_agent_id=current_agent_id,
            response=(
                "可用命令:\n"
                "/skills /memory /search /prompt /bootstrap /agents /switch /sessions /maintain /cron\n"
                "/yes /always /no /approvals\n"
                "/supervisor /review /verify /workflow"
            ),
        )
    if command == "/skills":
        app.skills_catalog.discover()
        if not app.skills_catalog.skills:
            return SlashCommandResult(True, "已发现的技能\n- (未找到技能)", current_agent_id)
        lines = ["已发现的技能"]
        for skill in app.skills_catalog.skills:
            lines.append(f"- {skill['invocation']}  {skill['name']} - {skill['description']}")
            lines.append(f"  path: {skill['path']}")
        return SlashCommandResult(True, "\n".join(lines), current_agent_id)
    if command == "/memory":
        return SlashCommandResult(True, _render_memory_command(app.memory_service, arg), current_agent_id)
    if command == "/search":
        if not arg:
            return SlashCommandResult(True, "用法: /search <query>", current_agent_id)
        results = app.memory_service.hybrid_search(arg)
        if not results:
            return SlashCommandResult(True, f"记忆搜索: {arg}\n- (无结果)", current_agent_id)
        lines = [f"记忆搜索: {arg}"]
        for item in results:
            lines.append(f"- [{item['score']:.4f}] {item['path']}")
            lines.append(f"  {item['snippet']}")
        return SlashCommandResult(True, "\n".join(lines), current_agent_id)
    if command == "/prompt":
        bootstrap_data = app.bootstrap_loader.load_all(mode="full")
        app.skills_catalog.discover()
        prompt = app.prompt_builder.build(
            bootstrap=bootstrap_data,
            skills_block=app.skills_catalog.format_prompt_block(),
            registered_tools_block=app.tools.format_prompt_block(),
            memory_context=app.turn_processor.build_memory_context("show prompt"),
            daily_digest_context=app.turn_processor.build_daily_digest_context(channel, user_id, current_agent_id),
            mode="full",
            agent_id=current_agent_id,
            channel=channel,
        )
        preview = prompt[:3000] if len(prompt) > 3000 else prompt
        suffix = f"\n\n... ({len(prompt) - 3000} more chars, total {len(prompt)})" if len(prompt) > 3000 else ""
        return SlashCommandResult(True, f"完整系统提示词\n{preview}{suffix}", current_agent_id)
    if command == "/bootstrap":
        bootstrap_data = app.bootstrap_loader.load_all(mode="full")
        if not bootstrap_data:
            return SlashCommandResult(True, "Bootstrap 文件\n- (未加载 Bootstrap 文件)", current_agent_id)
        lines = ["Bootstrap 文件"]
        for name, content in bootstrap_data.items():
            lines.append(f"- {name}: {len(content)} chars")
        return SlashCommandResult(True, "\n".join(lines), current_agent_id)
    if command == "/agents":
        lines = ["Agent Profiles"]
        for profile in app.agent_registry.list_profiles():
            marker = "*" if profile.agent_id == current_agent_id else " "
            lines.append(f"{marker} {profile.agent_id}  {profile.name}")
            lines.append(f"  {profile.personality}")
        return SlashCommandResult(True, "\n".join(lines), current_agent_id)
    if command == "/switch":
        target = arg.strip()
        if not target:
            return SlashCommandResult(True, "用法: /switch <agent_id>", current_agent_id)
        profile = app.agent_registry.get(target)
        if profile.agent_id != target:
            return SlashCommandResult(True, f"Unknown agent: {target}", current_agent_id)
        return SlashCommandResult(True, f"Switched agent to {profile.agent_id}", profile.agent_id)
    if command == "/sessions":
        rows = [
            row
            for row in app.session_manager.list_sessions()
            if row["channel"] == channel and row["user_id"] == user_id
        ]
        if not rows:
            return SlashCommandResult(True, "Sessions\n- (暂无 session)", current_agent_id)
        lines = ["Sessions"]
        for row in rows:
            lines.append(f"- {row['session_key']}")
            lines.append(
                f"  agent={row['agent_id']} messages={row['message_count']} last_active={row['last_active_at']}"
            )
        return SlashCommandResult(True, "\n".join(lines), current_agent_id)
    if command in {"/yes", "/always", "/no"}:
        if command == "/yes":
            return SlashCommandResult(True, app.tools.approve_pending_command(session_key, remember=False), current_agent_id)
        if command == "/always":
            return SlashCommandResult(True, app.tools.approve_pending_command(session_key, remember=True), current_agent_id)
        return SlashCommandResult(True, app.tools.reject_pending_command(session_key), current_agent_id)
    if command == "/approvals":
        lines = app.tools.format_pending_status_lines(session_key)
        return SlashCommandResult(True, "\n".join(lines) if lines else "pending: (none)", current_agent_id)
    if command == "/maintain":
        report = app.maintenance_service.run_once()
        return SlashCommandResult(
            True,
            "\n".join(
                [
                    "Maintenance",
                    f"- run_at: {report.run_at}",
                    f"- summary: {report.summary}",
                    f"- projection: {report.projection_path}",
                ]
            ),
            current_agent_id,
        )
    if command == "/cron":
        subparts = arg.split(maxsplit=1) if arg else []
        subcommand = subparts[0].lower() if subparts else "status"
        subarg = subparts[1] if len(subparts) > 1 else ""
        if subcommand in {"", "status", "list"}:
            rows = app.cron_scheduler.list_jobs()
            if not rows:
                return SlashCommandResult(True, "Cron Jobs\n- (未发现 cron 任务)", current_agent_id)
            lines = ["Cron Jobs"]
            for row in rows:
                enabled = "enabled" if row["enabled"] else "disabled"
                lines.append(f"- {row['job_id']}  {row['name']}  [{enabled}]")
                lines.append(
                    f"  expr={row['expr']} tz={row['tz']} agent={row['agent_id'] or app.agent_registry.default_agent_id}"
                )
                lines.append(f"  next={row['next_run_at'] or '-'}")
                lines.append(f"  last={row['last_run_at'] or '-'} status={row['last_status']}")
                if row["last_error"]:
                    lines.append(f"  error: {row['last_error']}")
            return SlashCommandResult(True, "\n".join(lines), current_agent_id)
        if subcommand == "reload":
            count = app.cron_scheduler.reload_jobs()
            return SlashCommandResult(True, f"cron 任务已重载: {count}", current_agent_id)
        if subcommand == "run":
            if not subarg:
                return SlashCommandResult(True, "用法: /cron run <job_id>", current_agent_id)
            ok, message = app.cron_scheduler.run_job_now(subarg.strip())
            return SlashCommandResult(True, message if ok else f"失败: {message}", current_agent_id)
        return SlashCommandResult(True, "用法: /cron [status|reload|run <job_id>]", current_agent_id)
    if command == "/supervisor":
        report = app.supervisor_workflow.get_current_report()
        if not report:
            return SlashCommandResult(True, "Supervisor Status\n- (无活跃 workflow)", current_agent_id)
        lines = [
            "Supervisor Status",
            f"- Task ID: {report.task_id}",
            f"- Phase: {report.phase.value}",
            f"- Intent: {report.intent.description[:60]}...",
            f"- Findings: {len(report.review_findings)}",
            f"- Verification results: {len(report.verification_results)}",
        ]
        if report.gate_decision:
            lines.append(f"- Decision: {report.gate_decision.overall.value}")
        return SlashCommandResult(True, "\n".join(lines), current_agent_id)
    if command == "/review":
        report = app.supervisor_workflow.get_current_report()
        if not report:
            return SlashCommandResult(True, "Review Last Execution\n- (无活跃 workflow)", current_agent_id)
        if not report.review_findings:
            return SlashCommandResult(True, "Review Last Execution\n- (无 review findings)", current_agent_id)
        lines = ["Review Last Execution"]
        for finding in report.review_findings:
            lines.append(f"- [{finding.severity.value}] {finding.rule_name}: {finding.message}")
            if finding.recommendation:
                lines.append(f"  -> {finding.recommendation}")
        return SlashCommandResult(True, "\n".join(lines), current_agent_id)
    if command == "/verify":
        app.supervisor_workflow.verify()
        report = app.supervisor_workflow.get_current_report()
        if not report:
            return SlashCommandResult(True, "Run Verification Gates\n- (无活跃 workflow)", current_agent_id)
        lines = ["Run Verification Gates"]
        for result in report.verification_results:
            lines.append(f"- {result.gate_name}: {result.status.value}")
            if result.details:
                lines.append(f"  {result.details}")
        return SlashCommandResult(True, "\n".join(lines), current_agent_id)
    if command == "/workflow":
        report = app.supervisor_workflow.get_current_report()
        if not report:
            return SlashCommandResult(True, "Workflow Report\n- (无活跃 workflow)", current_agent_id)
        lines = [
            "Workflow Report",
            f"- Report ID: {report.report_id}",
            f"- Task: {report.intent.description}",
            f"- Phase: {report.phase.value}",
            f"- Findings: {len(report.review_findings)} blocker(s), {len([f for f in report.review_findings if f.severity.value == 'warning'])} warning(s)",
        ]
        if report.gate_decision:
            lines.append(f"- Decision: {report.gate_decision.overall.value}")
            lines.append(f"- Reasoning: {report.gate_decision.reasoning}")
        return SlashCommandResult(True, "\n".join(lines), current_agent_id)
    return SlashCommandResult(True, "未知命令。可用命令：/help", current_agent_id)
