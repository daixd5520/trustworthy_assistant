from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from trustworthy_assistant.memory.service import TrustworthyMemoryService


@dataclass(slots=True)
class MaintenanceReport:
    run_at: str
    candidates: int
    disputed: int
    confirmed: int
    projection_path: str
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


class MaintenanceService:
    def __init__(self, memory_service: TrustworthyMemoryService) -> None:
        self.memory_service = memory_service

    def run_once(self) -> MaintenanceReport:
        projection_path = self.memory_service.sync_memory_markdown()
        stats = self.memory_service.get_stats()
        summary = (
            f"confirmed={stats['ledger_confirmed']} "
            f"candidate={stats['ledger_candidate']} "
            f"disputed={stats['ledger_disputed']}"
        )
        return MaintenanceReport(
            run_at=datetime.now(timezone.utc).isoformat(),
            candidates=stats["ledger_candidate"],
            disputed=stats["ledger_disputed"],
            confirmed=stats["ledger_confirmed"],
            projection_path=projection_path,
            summary=summary,
        )
