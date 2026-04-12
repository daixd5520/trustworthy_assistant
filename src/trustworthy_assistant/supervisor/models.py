"""Supervisor workflow data models."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class TaskPhase(str, Enum):
    INTENT = "intent"
    PLAN = "plan"
    EXECUTE = "execute"
    REVIEW = "review"
    VERIFY = "verify"
    SUMMARIZE = "summarize"


class Severity(str, Enum):
    BLOCKER = "blocker"
    WARNING = "warning"
    INFO = "info"


class GateStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"


class FinalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"
    NEEDS_VERIFICATION = "needs_verification"


@dataclass(frozen=True, slots=True)
class TaskIntent:
    task_id: str
    description: str
    requested_by: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {"task_id": self.task_id, "description": self.description, "requested_by": self.requested_by, "timestamp": self.timestamp}


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    task_id: str
    objective: str
    steps: list[str]
    affected_modules: list[str]
    involves_memory: bool = False
    involves_runtime: bool = False
    involves_eval: bool = False
    estimated_risk: str = "medium"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "steps": self.steps,
            "affected_modules": self.affected_modules,
            "involves_memory": self.involves_memory,
            "involves_runtime": self.involves_runtime,
            "involves_eval": self.involves_eval,
            "estimated_risk": self.estimated_risk,
            "created_at": self.created_at,
        }


@dataclass(slots=True)
class ReviewFinding:
    finding_id: str
    phase: TaskPhase
    severity: Severity
    rule_name: str
    message: str
    location: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "phase": self.phase.value if isinstance(self.phase, Enum) else self.phase,
            "severity": self.severity.value if isinstance(self.severity, Enum) else self.severity,
            "rule_name": self.rule_name,
            "message": self.message,
            "location": self.location,
            "recommendation": self.recommendation,
        }


@dataclass(slots=True)
class VerificationResult:
    gate_name: str
    status: GateStatus
    duration_ms: int = 0
    details: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "duration_ms": self.duration_ms,
            "details": self.details,
            "metrics": self.metrics,
        }


@dataclass(slots=True)
class GateDecision:
    decision_id: str
    overall: FinalDecision
    blocker_findings: list[ReviewFinding]
    warnings: list[ReviewFinding]
    verification_results: list[VerificationResult]
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "overall": self.overall.value if isinstance(self.overall, Enum) else self.overall,
            "blocker_findings": [f.to_dict() for f in self.blocker_findings],
            "warnings": [w.to_dict() for w in self.warnings],
            "verification_results": [v.to_dict() for v in self.verification_results],
            "reasoning": self.reasoning,
        }


@dataclass(slots=True)
class WorkflowReport:
    report_id: str
    task_id: str
    intent: TaskIntent
    execution_plan: ExecutionPlan | None = None
    execution_summary: str = ""
    review_findings: list[ReviewFinding] = field(default_factory=list)
    verification_results: list[VerificationResult] = field(default_factory=list)
    gate_decision: GateDecision | None = None
    phase: TaskPhase = TaskPhase.INTENT
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "task_id": self.task_id,
            "intent": self.intent.to_dict(),
            "execution_plan": self.execution_plan.to_dict() if self.execution_plan else None,
            "execution_summary": self.execution_summary,
            "review_findings": [f.to_dict() for f in self.review_findings],
            "verification_results": [v.to_dict() for v in self.verification_results],
            "gate_decision": self.gate_decision.to_dict() if self.gate_decision else None,
            "phase": self.phase.value if isinstance(self.phase, Enum) else self.phase,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
