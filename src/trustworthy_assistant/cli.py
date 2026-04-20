import atexit
import sys
from pathlib import Path

try:
    import readline
except ImportError:  # pragma: no cover - macOS/Linux normally provide readline
    readline = None

from trustworthy_assistant.app import build_app


CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


def colored_prompt() -> str:
    return f"{CYAN}{BOLD}You > {RESET}"


def print_info(text: str) -> None:
    print(f"{DIM}{text}{RESET}")


def print_section(title: str) -> None:
    print(f"\n{MAGENTA}{BOLD}--- {title} ---{RESET}")


def print_assistant(text: str) -> None:
    print(f"\n{GREEN}{BOLD}Assistant:{RESET} {text}\n")


def on_tool(name: str, detail: str) -> None:
    print(f"  {DIM}[tool: {name}] {detail}{RESET}")


def on_cron_event(message: str) -> None:
    print(f"\n{DIM}[cron] {message}{RESET}")


def setup_input_history(root_dir: Path) -> None:
    if readline is None:
        return
    history_file = root_dir / ".trustworthy_cli_history"
    try:
        readline.read_history_file(history_file)
    except FileNotFoundError:
        pass
    except OSError:
        return
    readline.set_history_length(1000)

    def _save_history() -> None:
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            readline.write_history_file(history_file)
        except OSError:
            pass

    atexit.register(_save_history)


def build_memory_context(memory_service, user_message: str, *, agent_id: str = "main", channel: str = "terminal", user_id: str = "local") -> str:
    results = memory_service.hybrid_search(
        user_message,
        top_k=3,
        agent_id=agent_id,
        channel=channel,
        user_id=user_id,
    )
    if not results:
        return ""
    return "\n".join(
        f"- [{item['path']}] (status={item['status']}, score={item['score']}) {item['snippet']}"
        for item in results
    )


def handle_runtime_command(app, command: str, arg: str, current_agent_id: str) -> tuple[bool, str]:
    current_session_key = app.session_manager.build_session_key(
        agent_id=current_agent_id,
        channel="terminal",
        user_id="local",
    )
    if command == "/agents":
        print_section("Agent Profiles")
        for profile in app.agent_registry.list_profiles():
            marker = "*" if profile.agent_id == current_agent_id else " "
            print(f" {marker} {BLUE}{profile.agent_id}{RESET}  {profile.name}")
            print(f"    {profile.personality}")
        return True, current_agent_id
    if command == "/switch":
        target = arg.strip()
        if not target:
            print(f"{YELLOW}用法: /switch <agent_id>{RESET}")
            return True, current_agent_id
        profile = app.agent_registry.get(target)
        if profile.agent_id != target:
            print(f"{YELLOW}Unknown agent: {target}{RESET}")
            return True, current_agent_id
        print(f"{GREEN}Switched agent to {profile.agent_id}{RESET}")
        return True, profile.agent_id
    if command == "/sessions":
        print_section("Sessions")
        rows = app.session_manager.list_sessions()
        if not rows:
            print(f"{DIM}(暂无 session){RESET}")
            return True, current_agent_id
        for row in rows:
            print(f"  {BLUE}{row['session_key']}{RESET}")
            print(f"    agent={row['agent_id']} messages={row['message_count']} last_active={row['last_active_at']}")
        return True, current_agent_id
    if command in {"/yes", "/always", "/no"}:
        print_section("Command Approval")
        if command == "/yes":
            result = app.tools.approve_pending_command(current_session_key, remember=False)
            print(result)
            return True, current_agent_id
        if command == "/always":
            result = app.tools.approve_pending_command(current_session_key, remember=True)
            print(result)
            return True, current_agent_id
        result = app.tools.reject_pending_command(current_session_key)
        print(result)
        return True, current_agent_id
    if command == "/approvals":
        print_section("Command Approvals")
        pending = app.tools.get_pending_command(current_session_key)
        prefixes = app.tools.list_approved_command_prefixes(current_session_key)
        if pending is None:
            print(f"{DIM}pending: (none){RESET}")
        else:
            print(f"  pending command: {pending.command}")
            print(f"  risk: {pending.risk}")
            print(f"  cwd: {pending.cwd}")
            print(f"  requested_at: {pending.created_at}")
        if prefixes:
            print("  remembered prefixes:")
            for prefix in prefixes:
                print(f"    - {prefix}")
        else:
            print(f"{DIM}remembered prefixes: (none){RESET}")
        return True, current_agent_id
    if command == "/maintain":
        print_section("Maintenance")
        report = app.maintenance_service.run_once()
        print(f"  run_at: {report.run_at}")
        print(f"  summary: {report.summary}")
        print(f"  projection: {report.projection_path}")
        return True, current_agent_id
    if command == "/cron":
        subparts = arg.split(maxsplit=1) if arg else []
        subcommand = subparts[0].lower() if subparts else "status"
        subarg = subparts[1] if len(subparts) > 1 else ""
        if subcommand in {"", "status", "list"}:
            print_section("Cron Jobs")
            rows = app.cron_scheduler.list_jobs()
            if not rows:
                print(f"{DIM}(未发现 cron 任务){RESET}")
                return True, current_agent_id
            for row in rows:
                status_color = GREEN if row["last_status"] == "ok" else YELLOW if row["last_status"] == "error" else DIM
                enabled = "enabled" if row["enabled"] else "disabled"
                print(f"  {BLUE}{row['job_id']}{RESET}  {row['name']}  [{enabled}]")
                print(f"    expr={row['expr']} tz={row['tz']} agent={row['agent_id'] or app.agent_registry.default_agent_id}")
                print(f"    next={row['next_run_at'] or '-'}")
                print(f"    last={row['last_run_at'] or '-'} status={status_color}{row['last_status']}{RESET}")
                if row["last_error"]:
                    print(f"    {DIM}error: {row['last_error']}{RESET}")
            return True, current_agent_id
        if subcommand == "reload":
            count = app.cron_scheduler.reload_jobs()
            print(f"{GREEN}cron 任务已重载: {count}{RESET}")
            return True, current_agent_id
        if subcommand == "run":
            if not subarg:
                print(f"{YELLOW}用法: /cron run <job_id>{RESET}")
                return True, current_agent_id
            ok, message = app.cron_scheduler.run_job_now(subarg.strip())
            print(f"{GREEN if ok else YELLOW}{message}{RESET}")
            return True, current_agent_id
        print(f"{YELLOW}用法: /cron [status|reload|run <job_id>]{RESET}")
        return True, current_agent_id
    if command == "/benchmarks":
        print_section("Benchmark Suite")
        reports = app.benchmark_suite.run_all(app.config.benchmark_dir)
        for item in reports:
            stats = item["report"]
            print(f"  {BLUE}{item['name']}{RESET}  confirmed={stats['confirmed']} rejected={stats['rejected']} hits={stats['searches_with_hits']}")
            print(f"    {item['description']}")
        return True, current_agent_id
    if command == "/supervisor":
        print_section("Supervisor Status")
        report = app.supervisor_workflow.get_current_report()
        if not report:
            print(f"{DIM}(无活跃 workflow){RESET}")
        else:
            print(f"  Task ID: {report.task_id}")
            print(f"  Phase: {report.phase.value}")
            print(f"  Intent: {report.intent.description[:60]}...")
            print(f"  Findings: {len(report.review_findings)}")
            print(f"  Verification results: {len(report.verification_results)}")
            if report.gate_decision:
                print(f"  Decision: {report.gate_decision.overall.value}")
        return True, current_agent_id
    if command == "/review":
        print_section("Review Last Execution")
        report = app.supervisor_workflow.get_current_report()
        if not report:
            print(f"{DIM}(无活跃 workflow){RESET}")
            return True, current_agent_id
        if not report.review_findings:
            print(f"{DIM}(无 review findings){RESET}")
        else:
            for f in report.review_findings:
                color = YELLOW if f.severity.value == "blocker" else DIM
                print(f"  {color}[{f.severity.value}]{RESET} {f.rule_name}: {f.message}")
                if f.recommendation:
                    print(f"    {DIM}-> {f.recommendation}{RESET}")
        return True, current_agent_id
    if command == "/verify":
        print_section("Run Verification Gates")
        app.supervisor_workflow.verify()
        report = app.supervisor_workflow.get_current_report()
        if report:
            for vr in report.verification_results:
                status_color = GREEN if vr.status.value == "passed" else YELLOW if vr.status.value == "failed" else DIM
                print(f"  {status_color}{vr.gate_name}: {vr.status.value}{RESET}")
                if vr.details:
                    print(f"    {DIM}{vr.details}{RESET}")
        return True, current_agent_id
    if command == "/workflow":
        print_section("Workflow Report")
        report = app.supervisor_workflow.get_current_report()
        if not report:
            print(f"{DIM}(无活跃 workflow){RESET}")
        else:
            print(f"  Report ID: {report.report_id}")
            print(f"  Task: {report.intent.description}")
            print(f"  Phase: {report.phase.value}")
            print(f"  Findings: {len(report.review_findings)} blocker(s), {len([f for f in report.review_findings if f.severity.value == 'warning'])} warning(s)")
            if report.gate_decision:
                print(f"  Decision: {GREEN if report.gate_decision.overall.value == 'approved' else YELLOW}{report.gate_decision.overall.value}{RESET}")
                print(f"  Reasoning: {report.gate_decision.reasoning}")
        return True, current_agent_id
    return False, current_agent_id


def handle_memory_command(memory_service, arg: str) -> bool:
    subparts = arg.split(maxsplit=1) if arg else []
    subcommand = subparts[0].lower() if subparts else "stats"
    subarg = subparts[1] if len(subparts) > 1 else ""
    if subcommand in {"", "stats"}:
        stats = memory_service.get_stats()
        print_section("记忆统计")
        print(f"  长期记忆 (MEMORY.md): {stats['evergreen_chars']} 字符")
        print(f"  每日文件: {stats['daily_files']}")
        print(f"  每日条目: {stats['daily_entries']}")
        print(f"  ledger 总数: {stats['ledger_total']}")
        print(f"  confirmed: {stats['ledger_confirmed']}  candidate: {stats['ledger_candidate']}  disputed: {stats['ledger_disputed']}")
        print(f"  review pending: {stats['ledger_review_pending']}")
        print(f"  trace 条数: {stats['trace_count']}")
        print(f"  projection: {stats['managed_projection_path']}")
        return True
    if subcommand == "list":
        print_section("Ledger Memories")
        for row in memory_service.list_memories(limit=10):
            print(f"  {BLUE}{row['memory_id']}{RESET} [{row['status']}] {row['slot']}")
            print(f"    {row['summary']}")
        return True
    if subcommand == "candidates":
        print_section("Candidate Memories")
        rows = memory_service.list_candidates(limit=10)
        if not rows:
            print(f"{DIM}(无候选记忆){RESET}")
            return True
        for row in rows:
            print(f"  {YELLOW}{row['memory_id']}{RESET} [{row['status']}] {row['slot']}")
            print(f"    {row['summary']}")
        return True
    if subcommand == "trace":
        print_section("Last Retrieval Trace")
        print(memory_service.format_last_trace())
        return True
    if subcommand == "conflicts":
        print_section("Memory Conflicts")
        rows = memory_service.list_conflicts(limit=10)
        if not rows:
            print(f"{DIM}(无冲突){RESET}")
            return True
        for row in rows:
            print(f"  {YELLOW}{row['memory_id']}{RESET} [{row['status']}] {row['slot']}")
            print(f"    {row['summary']}")
            print(f"    conflicts_with={', '.join(row.get('conflicts_with', [])) or '-'}")
        return True
    if subcommand == "confirm":
        if not subarg:
            print(f"{YELLOW}用法: /memory confirm <memory_id>{RESET}")
            return True
        ok, message = memory_service.confirm_memory(subarg.strip())
        print(f"{GREEN if ok else YELLOW}{message}{RESET}")
        return True
    if subcommand == "reject":
        if not subarg:
            print(f"{YELLOW}用法: /memory reject <memory_id>{RESET}")
            return True
        ok, message = memory_service.reject_memory(subarg.strip())
        print(f"{GREEN if ok else YELLOW}{message}{RESET}")
        return True
    if subcommand == "forget":
        if not subarg:
            print(f"{YELLOW}用法: /memory forget <memory_id>{RESET}")
            return True
        ok, message = memory_service.forget_memory(subarg.strip())
        print(f"{GREEN if ok else YELLOW}{message}{RESET}")
        return True
    if subcommand == "show":
        if not subarg:
            print(f"{YELLOW}用法: /memory show <memory_id>{RESET}")
            return True
        print_section("Memory Detail")
        print(memory_service.explain_memory(subarg.strip()))
        return True
    if subcommand == "sync":
        print(f"{GREEN}Memory projection synced: {memory_service.sync_memory_markdown()}{RESET}")
        return True
    print(f"{YELLOW}用法: /memory [stats|list|candidates|trace|conflicts|show <id>|confirm <id>|reject <id>|forget <id>|sync]{RESET}")
    return True


def handle_dream_command(app, arg: str, current_agent_id: str) -> bool:
    subparts = arg.split(maxsplit=1) if arg else []
    subcommand = subparts[0].lower() if subparts else "status"
    subarg = subparts[1].strip() if len(subparts) > 1 else ""
    if subcommand in {"", "status", "plans"}:
        print_section("Nightly Dream Plans")
        rows = app.dream_service.repository.load_plans(agent_id=current_agent_id, channel="terminal", user_id="local", limit=10)
        if not rows:
            print(f"{DIM}(暂无 dream 计划){RESET}")
            return True
        for row in rows:
            print(
                f"  {BLUE}{row.get('job_id','-')}{RESET} "
                f"status={row.get('status','-')} target={row.get('target_date','-')}"
            )
            print(
                f"    agent={row.get('agent_id','-')} channel={row.get('channel','-')} "
                f"user={row.get('user_id','-')}"
            )
            print(f"    scheduled_for={row.get('scheduled_for','-')}")
        return True
    if subcommand == "runs":
        print_section("Nightly Dream Runs")
        rows = app.dream_service.repository.load_runs(agent_id=current_agent_id, channel="terminal", user_id="local", limit=10)
        if not rows:
            print(f"{DIM}(暂无 dream 运行记录){RESET}")
            return True
        for row in rows:
            color = GREEN if row.get("status") == "ok" else YELLOW
            print(
                f"  {color}{row.get('run_id','-')}{RESET} "
                f"status={row.get('status','-')} target={row.get('target_date','-')}"
            )
            print(
                f"    agent={row.get('agent_id','-')} channel={row.get('channel','-')} "
                f"user={row.get('user_id','-')}"
            )
            print(
                f"    memories={row.get('new_memory_count',0)} lessons={row.get('new_lesson_count',0)} "
                f"report={row.get('report_path','-') or '-'}"
            )
            if row.get("error"):
                print(f"    {DIM}error: {row.get('error')}{RESET}")
        return True
    if subcommand == "lessons":
        print_section("Nightly Dream Lessons")
        active_rows = app.dream_service.repository.load_lessons(
            agent_id=current_agent_id,
            channel="terminal",
            user_id="local",
            status="active",
            limit=10,
        )
        archived_rows = app.dream_service.repository.load_lessons(
            agent_id=current_agent_id,
            channel="terminal",
            user_id="local",
            status="archived",
            limit=10,
        )
        if not active_rows and not archived_rows:
            print(f"{DIM}(暂无 lessons){RESET}")
            return True
        print(f"{GREEN}Active:{RESET}")
        if active_rows:
            for row in active_rows:
                print(
                    f"  {BLUE}{row.get('lesson_id','-')}{RESET} "
                    f"[{row.get('scope','workflow')}] confidence={row.get('confidence',0)} "
                    f"importance={row.get('importance',0)}"
                )
                print(f"    {row.get('summary','')}")
        else:
            print(f"  {DIM}(none){RESET}")
        print(f"{YELLOW}Archived:{RESET}")
        if archived_rows:
            for row in archived_rows:
                print(
                    f"  {BLUE}{row.get('lesson_id','-')}{RESET} "
                    f"[{row.get('scope','workflow')}] confidence={row.get('confidence',0)} "
                    f"importance={row.get('importance',0)}"
                )
                print(f"    {row.get('summary','')}")
        else:
            print(f"  {DIM}(none){RESET}")
        return True
    if subcommand == "run":
        try:
            result = app.dream_service.run_manual(
                agent_id=current_agent_id,
                channel="terminal",
                user_id="local",
                target_date=subarg,
            )
        except Exception as exc:
            print(f"{YELLOW}dream 手动运行失败: {exc}{RESET}")
            return True
        print_section("Nightly Dream Run")
        print(f"{GREEN}status={result.get('status','-')}{RESET} target={result.get('target_date','-')}")
        print(
            f"memories={result.get('new_memory_count',0)} "
            f"lessons={result.get('new_lesson_count',0)}"
        )
        if result.get("report_path"):
            print(f"report={result.get('report_path')}")
        return True
    if subcommand == "report":
        report = app.dream_service.get_report(
            agent_id=current_agent_id,
            channel="terminal",
            user_id="local",
            target_date=subarg,
        )
        if not report:
            print(f"{DIM}(暂无 dream report){RESET}")
            return True
        print_section(f"Nightly Dream Report: {report.get('target_date','-')}")
        print(f"{DIM}{report.get('report_path','')}{RESET}")
        print(report.get("content", "").strip())
        return True
    if subcommand == "latest":
        report = app.dream_service.get_report(
            agent_id=current_agent_id,
            channel="terminal",
            user_id="local",
            target_date="",
        )
        if not report:
            print(f"{DIM}(暂无最近 dream report){RESET}")
            return True
        print_section(f"Nightly Dream Latest: {report.get('target_date','-')}")
        print(f"{DIM}{report.get('report_path','')}{RESET}")
        print(report.get("content", "").strip())
        return True
    if subcommand == "prune":
        summary = app.dream_service.prune_lessons(
            agent_id=current_agent_id,
            channel="terminal",
            user_id="local",
        )
        print_section("Nightly Dream Prune")
        print(
            f"{GREEN}scanned={summary.get('scanned',0)}{RESET} "
            f"decayed={summary.get('decayed',0)} archived={summary.get('archived',0)}"
        )
        return True
    print(f"{YELLOW}用法: /dream [plans|runs|lessons|run [today|yesterday|YYYY-MM-DD]|report [today|yesterday|YYYY-MM-DD]|latest|prune]{RESET}")
    return True


def handle_repl_command(app, cmd: str, bootstrap_data: dict[str, str], skills_block: str, current_agent_id: str) -> bool:
    parts = cmd.strip().split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    if command == "/skills":
        print_section("已发现的技能")
        if not app.skills_catalog.skills:
            print(f"{DIM}(未找到技能){RESET}")
        else:
            for skill in app.skills_catalog.skills:
                print(f"  {BLUE}{skill['invocation']}{RESET}  {skill['name']} - {skill['description']}")
                print(f"    {DIM}path: {skill['path']}{RESET}")
        return True
    if command == "/memory":
        return handle_memory_command(app.memory_service, arg)
    if command == "/dream":
        return handle_dream_command(app, arg, current_agent_id)
    if command == "/search":
        if not arg:
            print(f"{YELLOW}用法: /search <query>{RESET}")
            return True
        print_section(f"记忆搜索: {arg}")
        results = app.memory_service.hybrid_search(
            arg,
            agent_id=current_agent_id,
            channel="terminal",
            user_id="local",
        )
        if not results:
            print(f"{DIM}(无结果){RESET}")
        else:
            for item in results:
                color = GREEN if item["score"] > 0.3 else DIM
                print(f"  {color}[{item['score']:.4f}]{RESET} {item['path']}")
                print(f"    {item['snippet']}")
        return True
    if command == "/prompt":
        print_section("完整系统提示词")
        prompt = app.prompt_builder.build(
            bootstrap=bootstrap_data,
            skills_block=skills_block,
            memory_context=build_memory_context(
                app.memory_service,
                "show prompt",
                agent_id=current_agent_id,
                channel="terminal",
                user_id="local",
            ),
        )
        print(prompt[:3000] if len(prompt) > 3000 else prompt)
        if len(prompt) > 3000:
            print(f"\n{DIM}... ({len(prompt) - 3000} more chars, total {len(prompt)}){RESET}")
        print(f"\n{DIM}提示词总长度: {len(prompt)} 字符{RESET}")
        return True
    if command == "/bootstrap":
        print_section("Bootstrap 文件")
        if not bootstrap_data:
            print(f"{DIM}(未加载 Bootstrap 文件){RESET}")
        else:
            for name, content in bootstrap_data.items():
                print(f"  {BLUE}{name}{RESET}: {len(content)} chars")
        return True
    return False


def run() -> None:
    app = build_app(on_tool=on_tool, on_cron_event=on_cron_event)
    if not app.config.anthropic_api_key:
        print(f"{YELLOW}错误: 未设置 ANTHROPIC_API_KEY.{RESET}")
        sys.exit(1)
    if not app.config.workspace_dir.is_dir():
        print(f"{YELLOW}错误: 未找到工作区目录: {app.config.workspace_dir}{RESET}")
        sys.exit(1)
    setup_input_history(app.config.root_dir)
    bootstrap_data = app.bootstrap_loader.load_all(mode="full")
    app.skills_catalog.discover()
    skills_block = app.skills_catalog.format_prompt_block()
    current_agent_id = app.agent_registry.default_agent_id
    app.cron_scheduler.start()
    print_info("=" * 64)
    print_info("  trustworthy_assistant  |  Production Memory Edition")
    print_info(f"  Model: {app.config.model_id}")
    print_info(f"  Workspace: {app.config.workspace_dir}")
    print_info(f"  Cron jobs loaded: {len(app.cron_scheduler.list_jobs())}")
    print_info("  命令: /skills /memory /dream /search /prompt /bootstrap /agents /switch /sessions /maintain /cron /benchmarks")
    print_info("  审批: /yes /always /no /approvals")
    print_info("  supervisor: /supervisor /review /verify /workflow")
    print_info("  memory 子命令: stats list candidates trace conflicts show confirm reject forget sync")
    print_info("  dream 子命令: plans runs lessons run [date] report [date] latest prune")
    print_info("=" * 64)
    try:
        while True:
            try:
                user_input = input(colored_prompt()).strip()
            except (KeyboardInterrupt, EOFError):
                print(f"\n{DIM}再见.{RESET}")
                break
            if not user_input:
                continue
            if user_input.lower() in {"quit", "exit"}:
                print(f"\n{DIM}再见.{RESET}")
                break
            if user_input.startswith("/"):
                parts = user_input.strip().split(maxsplit=1)
                runtime_handled, current_agent_id = handle_runtime_command(app, parts[0].lower(), parts[1] if len(parts) > 1 else "", current_agent_id)
                if runtime_handled:
                    continue
            if user_input.startswith("/") and handle_repl_command(app, user_input, bootstrap_data, skills_block, current_agent_id):
                continue
            agent = app.agent_registry.get(current_agent_id)
            
            print(f"\n{GREEN}{BOLD}Assistant:{RESET} ", end="", flush=True)
            accumulated_text = []
            def on_text(text: str):
                print(text, end="", flush=True)
                accumulated_text.append(text)
            
            result = app.turn_processor.process_turn_stream(
                user_input, agent=agent, channel="terminal", user_id="local", on_text=on_text
            )
            
            if result.recalled_memory:
                print_info("\n  [自动召回] 找到相关记忆")
            if result.errors:
                print(f"\n{YELLOW}API Error: {'; '.join(result.errors)}{RESET}\n")
                continue
            print("\n")
    finally:
        app.cron_scheduler.stop()


if __name__ == "__main__":
    run()
