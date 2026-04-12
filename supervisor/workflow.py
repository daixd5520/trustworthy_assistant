"""Supervisor workflow orchestration."""

import uuid
from datetime import datetime, timezone
from typing import Any

from trustworthy_assistant.supervisor.gates import (
    GateRegistry,
    GATE_REGISTRY,
    aggregate_gate_results,
    register_default_gates,
)
from trustworthy_assistant.supervisor.models import (
    ExecutionPlan,
    FinalDecision,
    GateDecision,
    GateStatus,
    ReviewFinding,
    Severity,
    TaskIntent,
    TaskPhase,
    VerificationResult,
    WorkflowReport,
)
from trustworthy_assistant.supervisor.policies import DEFAULT_POLICIES, SupervisorPolicies
from trustworthy_assistant.supervisor.reviewer import RuleBasedReviewer


class SupervisorWorkflow:
    """Orchestrates the supervisor workflow: plan -> execute -> review -> verify -> summarize."""

    def __init__(
        self,
        policies: SupervisorPolicies | None = None,
        gate_registry: GateRegistry | None = None,
    ) -> None:
        self.policies = policies or DEFAULT_POLICIES
        self.gate_registry = gate_registry or GATE_REGISTRY
        self.reviewer = RuleBasedReviewer(self.policies)
        self._current_report: WorkflowReport | None = None
        register_default_gates()

    def _new_id(self, prefix: str = "wf") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def start_task(
        self,
        description: str,
        requested_by: str = "user",
        context: dict[str, Any] | None = None,
    ) -> WorkflowReport:
        """Start a new task workflow."""
        task_id = self._new_id("task")
        intent = TaskIntent(
            task_id=task_id,
            description=description,
            requested_by=requested_by,
        )
        self._current_report = WorkflowReport(
            report_id=self._new_id("rpt"),
            task_id=task_id,
            intent=intent,
            phase=TaskPhase.INTENT,
        )
        return self._current_report

    def plan(
        self,
        objective: str,
        steps: list[str],
        affected_modules: list[str],
        involves_memory: bool = False,
        involves_runtime: bool = False,
        involves_eval: bool = False,
        estimated_risk: str = "medium",
    ) -> WorkflowReport:
        """Create an execution plan for the current task."""
        if not self._current_report:
            raise ValueError("No active task - call start_task() first")

        plan = ExecutionPlan(
            task_id=self._current_report.task_id,
            objective=objective,
            steps=steps,
            affected_modules=affected_modules,
            involves_memory=involves_memory,
            involves_runtime=involves_runtime,
            involves_eval=involves_eval,
            estimated_risk=estimated_risk,
        )

        self._current_report.execution_plan = plan
        self._current_report.phase = TaskPhase.PLAN

        plan_findings = self.reviewer.review_plan(plan)
        self._current_report.review_findings.extend(plan_findings)

        return self._current_report

    def execute(self, summary: str) -> WorkflowReport:
        """Record execution summary and run post-execution review."""
        if not self._current_report:
            raise ValueError("No active task - call start_task() first")

        self._current_report.execution_summary = summary
        self._current_report.phase = TaskPhase.EXECUTE

        if self._current_report.execution_plan:
            exec_findings = self.reviewer.review_execution(
                self._current_report.execution_plan,
                summary,
                has_verification=bool(self._current_report.verification_results),
            )
            all_findings = self.reviewer.aggregate_findings(
                self._current_report.review_findings, exec_findings
            )
            self._current_report.review_findings = all_findings

        return self._current_report

    def review(self) -> WorkflowReport:
        """Mark current phase as review - findings already collected during plan/execute."""
        if not self._current_report:
            raise ValueError("No active task - call start_task() first")

        self._current_report.phase = TaskPhase.REVIEW
        return self._current_report

    def verify(self, gate_names: list[str] | None = None) -> WorkflowReport:
        """Run verification gates."""
        if not self._current_report:
            raise ValueError("No active task - call start_task() first")

        self._current_report.phase = TaskPhase.VERIFY

        if gate_names is None:
            if self._current_report.execution_plan:
                gate_names = self.policies.requires_gate_for_plan(
                    self._current_report.execution_plan
                )
            else:
                gate_names = self.gate_registry.list_gates()

        for gate_name in gate_names:
            result = self.gate_registry.run(gate_name)
            self._current_report.verification_results.append(result)

        return self._current_report

    def finalize(self) -> WorkflowReport:
        """Make final decision based on findings and verification results."""
        if not self._current_report:
            raise ValueError("No active task - call start_task() first")

        self._current_report.phase = TaskPhase.SUMMARIZE

        blockers = self.policies.blockers_from_findings(self._current_report.review_findings)
        warnings = self.policies.warnings_from_findings(self._current_report.review_findings)

        verif_summary = aggregate_gate_results(self._current_report.verification_results)
        any_verif_failed = verif_summary.get("any_failed", False)

        if blockers:
            if any_verif_failed:
                overall = FinalDecision.REJECTED
                reasoning = f"Rejected: {len(blockers)} blocker(s) and verification failures"
            else:
                overall = FinalDecision.NEEDS_REVISION
                reasoning = f"Needs revision: {len(blockers)} blocker(s) found"
        elif any_verif_failed:
            overall = FinalDecision.NEEDS_VERIFICATION
            reasoning = "Verification failures detected"
        elif warnings:
            overall = FinalDecision.APPROVED
            reasoning = f"Approved with {len(warnings)} warning(s)"
        else:
            overall = FinalDecision.APPROVED
            reasoning = "No blockers or warnings - approved"

        gate_decision = GateDecision(
            decision_id=self._new_id("dec"),
            overall=overall,
            blocker_findings=blockers,
            warnings=warnings,
            verification_results=self._current_report.verification_results,
            reasoning=reasoning,
        )

        self._current_report.gate_decision = gate_decision
        self._current_report.updated_at = self._now()

        return self._current_report

    def get_current_report(self) -> WorkflowReport | None:
        """Get the current workflow report."""
        return self._current_report

    def reset(self) -> None:
        """Reset the current workflow."""
        self._current_report = None
