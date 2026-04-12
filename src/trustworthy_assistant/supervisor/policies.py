"""Supervisor policies and rules for gate decisions."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trustworthy_assistant.supervisor.models import ExecutionPlan, ReviewFinding, VerificationResult


@dataclass(frozen=True)
class PolicyConfig:
    """Configuration for a single policy rule."""

    name: str
    enabled: bool = True
    requires_verification: bool = False
    min_verification_confidence: float = 0.8
    blocks_on_fail: bool = True


@dataclass
class SupervisorPolicies:
    """Collection of all supervisor policies."""

    memory_change_strict: bool = True
    require_verification_for_runtime: bool = True
    require_verification_for_eval: bool = True
    allow_unverified_low_risk: bool = False
    max_review_findings_before_block: int = 3

    # Policy definitions
    policies: dict[str, PolicyConfig] = field(default_factory=lambda: {
        "memory_governance": PolicyConfig(
            name="memory_governance",
            requires_verification=True,
            blocks_on_fail=True,
        ),
        "runtime_safety": PolicyConfig(
            name="runtime_safety",
            requires_verification=True,
            blocks_on_fail=True,
        ),
        "eval_coverage": PolicyConfig(
            name="eval_coverage",
            requires_verification=True,
            blocks_on_fail=False,
        ),
        "minimal_diff": PolicyConfig(
            name="minimal_diff",
            requires_verification=False,
            blocks_on_fail=False,
        ),
        "architecture_constraints": PolicyConfig(
            name="architecture_constraints",
            requires_verification=True,
            blocks_on_fail=True,
        ),
        "regression_prevention": PolicyConfig(
            name="regression_prevention",
            requires_verification=True,
            blocks_on_fail=True,
        ),
    })

    def get_policy(self, name: str) -> PolicyConfig | None:
        return self.policies.get(name)

    def requires_gate_for_plan(self, plan: "ExecutionPlan") -> list[str]:
        """Return list of gate names that should be run for this execution plan."""
        required_gates = []

        if plan.involves_memory:
            required_gates.append("memory_governance")
            if self.memory_change_strict:
                required_gates.append("regression_prevention")

        if plan.involves_runtime:
            required_gates.append("runtime_safety")
            if self.require_verification_for_runtime:
                required_gates.append("regression_prevention")

        if plan.involves_eval:
            required_gates.append("eval_coverage")
            if self.require_verification_for_eval:
                required_gates.append("regression_prevention")

        if plan.estimated_risk == "high":
            required_gates.extend(["runtime_safety", "regression_prevention"])

        return list(set(required_gates))

    def blockers_from_findings(
        self, findings: list["ReviewFinding"]
    ) -> list["ReviewFinding"]:
        """Filter findings that should block execution."""
        blockers = []
        for f in findings:
            policy = self.policies.get(f.rule_name)
            if policy and policy.blocks_on_fail:
                blockers.append(f)
        return blockers

    def warnings_from_findings(
        self, findings: list["ReviewFinding"]
    ) -> list["ReviewFinding"]:
        """Filter findings that are warnings but not blockers."""
        return [
            f
            for f in findings
            if not (self.policies.get(f.rule_name) or PolicyConfig(name="")).blocks_on_fail
        ]

    def can_pass_without_verification(
        self, plan: "ExecutionPlan", findings: list["ReviewFinding"]
    ) -> bool:
        """Check if the workflow can pass without running verification gates."""
        if self.blockers_from_findings(findings):
            return False

        required_gates = self.requires_gate_for_plan(plan)
        for gate in required_gates:
            policy = self.policies.get(gate)
            if policy and policy.requires_verification:
                return False

        if plan.estimated_risk == "high":
            return False

        return self.allow_unverified_low_risk


# Global default policies instance
DEFAULT_POLICIES = SupervisorPolicies()
