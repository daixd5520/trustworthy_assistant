from dataclasses import asdict, dataclass, field
from pathlib import Path

from trustworthy_assistant.memory.service import TrustworthyMemoryService


@dataclass(frozen=True, slots=True)
class ReplayStep:
    action: str
    content: str = ""
    category: str = "general"
    memory_id: str = ""
    query: str = ""


@dataclass(slots=True)
class ReplayObservation:
    step_index: int
    action: str
    outcome: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class ReplayReport:
    total_steps: int
    writes: int
    candidates_created: int
    confirmed: int
    rejected: int
    archived: int
    searches_with_hits: int
    projection_updates: int
    final_stats: dict
    observations: list[ReplayObservation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_steps": self.total_steps,
            "writes": self.writes,
            "candidates_created": self.candidates_created,
            "confirmed": self.confirmed,
            "rejected": self.rejected,
            "archived": self.archived,
            "searches_with_hits": self.searches_with_hits,
            "projection_updates": self.projection_updates,
            "final_stats": self.final_stats,
            "observations": [item.to_dict() for item in self.observations],
        }

    def render_text(self) -> str:
        lines = [
            "Replay Report",
            f"- total_steps: {self.total_steps}",
            f"- writes: {self.writes}",
            f"- candidates_created: {self.candidates_created}",
            f"- confirmed: {self.confirmed}",
            f"- rejected: {self.rejected}",
            f"- archived: {self.archived}",
            f"- searches_with_hits: {self.searches_with_hits}",
            f"- projection_updates: {self.projection_updates}",
            f"- final_confirmed: {self.final_stats.get('ledger_confirmed', 0)}",
            f"- final_candidates: {self.final_stats.get('ledger_candidate', 0)}",
            "",
            "Observations:",
        ]
        for item in self.observations:
            lines.append(f"- step={item.step_index} action={item.action} outcome={item.outcome} detail={item.detail}")
        return "\n".join(lines)


class ReplayHarness:
    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir

    def run(self, steps: list[ReplayStep]) -> ReplayReport:
        service = TrustworthyMemoryService(self.workspace_dir)
        report = ReplayReport(
            total_steps=len(steps),
            writes=0,
            candidates_created=0,
            confirmed=0,
            rejected=0,
            archived=0,
            searches_with_hits=0,
            projection_updates=0,
            final_stats={},
        )
        projection_before = service.load_evergreen()

        for index, step in enumerate(steps, start=1):
            if step.action == "write":
                outcome = service.write_memory(step.content, category=step.category)
                report.writes += 1
                report.observations.append(ReplayObservation(index, step.action, "ok", outcome))
            elif step.action == "ingest":
                staged = service.ingest_user_message(step.content, session_key="replay")
                report.candidates_created += len(staged)
                report.observations.append(
                    ReplayObservation(index, step.action, "ok", f"staged={len(staged)}")
                )
            elif step.action == "confirm":
                memory_id = step.memory_id or self._latest_candidate_id(service)
                ok, message = service.confirm_memory(memory_id)
                if ok:
                    report.confirmed += 1
                report.observations.append(
                    ReplayObservation(index, step.action, "ok" if ok else "error", message)
                )
            elif step.action == "reject":
                memory_id = step.memory_id or self._latest_candidate_id(service)
                ok, message = service.reject_memory(memory_id)
                if ok:
                    report.rejected += 1
                report.observations.append(
                    ReplayObservation(index, step.action, "ok" if ok else "error", message)
                )
            elif step.action == "forget":
                memory_id = step.memory_id or self._latest_active_memory_id(service)
                ok, message = service.forget_memory(memory_id)
                if ok:
                    report.archived += 1
                report.observations.append(
                    ReplayObservation(index, step.action, "ok" if ok else "error", message)
                )
            elif step.action == "search":
                results = service.hybrid_search(step.query or step.content, top_k=3)
                if results:
                    report.searches_with_hits += 1
                report.observations.append(
                    ReplayObservation(index, step.action, "ok", f"hits={len(results)}")
                )
            elif step.action == "sync":
                service.sync_memory_markdown()
                report.observations.append(ReplayObservation(index, step.action, "ok", "projection synced"))
            else:
                report.observations.append(ReplayObservation(index, step.action, "ignored", "unknown action"))

            projection_after = service.load_evergreen()
            if projection_after != projection_before:
                report.projection_updates += 1
                projection_before = projection_after

        report.final_stats = service.get_stats()
        return report

    @staticmethod
    def _latest_candidate_id(service: TrustworthyMemoryService) -> str:
        candidates = service.list_candidates(limit=1)
        if candidates:
            return candidates[0]["memory_id"]
        return ReplayHarness._latest_active_memory_id(service)

    @staticmethod
    def _latest_active_memory_id(service: TrustworthyMemoryService) -> str:
        memories = service.list_memories(limit=20)
        for row in memories:
            if row.get("status") != "archived":
                return row["memory_id"]
        return ""
