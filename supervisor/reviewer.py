"""Rule-based reviewer for supervisor workflow."""

import uuid
from typing import Any

from trustworthy_assistant.supervisor.models import (
    ExecutionPlan,
    ReviewFinding,
    Severity,
    TaskPhase,
)
from trustworthy_assistant.supervisor.policies import SupervisorPolicies


class RuleBasedReviewer:
    """Deterministic rule-based reviewer for execution plans and summaries."""

    def __init__(self, policies: SupervisorPolicies | None = None) -> None:
        self.policies = policies or SupervisorPolicies()

    def _new_id(self) -> str:
        return f"rv_{uuid.uuid4().hex[:12]}"

    def _severity_for_rule(self, rule_name: str) -> Severity:
        policy = self.policies.get_policy(rule_name)
        if policy and policy.blocks_on_fail:
            return Severity.BLOCKER
        return Severity.WARNING

    def review_plan(
        self,
        plan: ExecutionPlan,
        context: dict[str, Any] | None = None,
    ) -> list[ReviewFinding]:
        """Review an execution plan before execution."""
        findings: list[ReviewFinding] = []
        context = context or {}

        if not plan.steps:
            findings.append(
                ReviewFinding(
                    finding_id=self._new_id(),
                    phase=TaskPhase.PLAN,
                    severity=Severity.BLOCKER,
                    rule_name="minimal_diff",
                    message="Execution plan has no steps defined",
                    location="plan.steps",
                )
            )

        if plan.involves_memory and plan.involves_runtime:
            findings.append(
                ReviewFinding(
                    finding_id=self._new_id(),
                    phase=TaskPhase.PLAN,
                    severity=Severity.WARNING,
                    rule_name="architecture_constraints",
                    message="Changes touch both memory and runtime - ensure no circular dependencies",
                    location="plan.affected_modules",
                    recommendation="Consider splitting into separate changes",
                )
            )

        if len(plan.affected_modules) > 5 and plan.estimated_risk != "high":
            findings.append(
                ReviewFinding(
                    finding_id=self._new_id(),
                    phase=TaskPhase.PLAN,
                    severity=Severity.WARNING,
                    rule_name="minimal_diff",
                    message=f"Changes affect {len(plan.affected_modules)} modules - verify minimal diff principle",
                    location="plan.affected_modules",
                    recommendation="Consider narrower scope if possible",
                )
            )

        if plan.involves_memory:
            if not any(
                "governance" in str(m).lower() or "memory" in str(m).lower()
                for m in plan.affected_modules
            ):
                findings.append(
                    ReviewFinding(
                        finding_id=self._new_id(),
                        phase=TaskPhase.PLAN,
                        severity=self._severity_for_rule("memory_governance"),
                        rule_name="memory_governance",
                        message="Changes involve memory system but may not maintain projection compatibility",
                        location="memory/service.py",
                        recommendation="Ensure MEMORY.md projection remains valid",
                    )
                )

        if plan.involves_eval:
            findings.append(
                ReviewFinding(
                    finding_id=self._new_id(),
                    phase=TaskPhase.PLAN,
                    severity=Severity.INFO,
                    rule_name="eval_coverage",
                    message="Changes involve eval module - ensure tests are added or updated",
                    location="eval/",
                    recommendation="Run benchmark suite after changes",
                )
            )

        return findings

    def review_execution(
        self,
        plan: ExecutionPlan,
        execution_summary: str,
        has_verification: bool = False,
        context: dict[str, Any] | None = None,
    ) -> list[ReviewFinding]:
        """Review an execution summary after execution."""
        findings: list[ReviewFinding] = []
        context = context or {}
        execution_lower = execution_summary.lower()

        if not execution_summary or len(execution_summary.strip()) < 20:
            findings.append(
                ReviewFinding(
                    finding_id=self._new_id(),
                    phase=TaskPhase.EXECUTE,
                    severity=Severity.BLOCKER,
                    rule_name="minimal_diff",
                    message="Execution summary is empty or too brief",
                    location="execution_summary",
                    recommendation="Provide a clear summary of what was done",
                )
            )

        if plan.involves_memory and "memory" not in execution_lower:
            findings.append(
                ReviewFinding(
                    finding_id=self._new_id(),
                    phase=TaskPhase.EXECUTE,
                    severity=Severity.BLOCKER,
                    rule_name="memory_governance",
                    message="Plan involved memory but summary doesn't mention it",
                    location="memory/",
                    recommendation="Document memory-related changes",
                )
            )

        if plan.involves_runtime and "runtime" not in execution_lower:
            findings.append(
                ReviewFinding(
                    finding_id=self._new_id(),
                    phase=TaskPhase.EXECUTE,
                    severity=Severity.WARNING,
                    rule_name="runtime_safety",
                    message="Plan involved runtime but summary doesn't mention it",
                    location="runtime/",
                )
            )

        blockers = self.policies.blockers_from_findings(findings)
        if not has_verification and blockers:
            findings.append(
                ReviewFinding(
                    finding_id=self._new_id(),
                    phase=TaskPhase.EXECUTE,
                    severity=Severity.BLOCKER,
                    rule_name="regression_prevention",
                    message=f"{len(blockers)} blocker(s) found but no verification was run",
                    recommendation="Run verification gates before proceeding",
                )
            )

        if "error" in execution_lower or "fail" in execution_lower:
            findings.append(
                ReviewFinding(
                    finding_id=self._new_id(),
                    phase=TaskPhase.EXECUTE,
                    severity=Severity.BLOCKER,
                    rule_name="runtime_safety",
                    message="Execution summary mentions errors or failures",
                    location="execution_summary",
                    recommendation="Resolve errors before final approval",
                )
            )

        return findings

    def aggregate_findings(
        self, plan_findings: list[ReviewFinding], exec_findings: list[ReviewFinding]
    ) -> list[ReviewFinding]:
        """Aggregate and deduplicate findings."""
        seen: set[str] = set()
        combined = plan_findings + exec_findings
        unique: list[ReviewFinding] = []

        for f in combined:
            key = f"{f.phase.value}:{f.rule_name}:{f.message[:50]}"
            if key not in seen:
                seen.add(key)
                unique.append(f)

        return unique
