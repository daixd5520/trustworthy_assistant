"""Verification gates for supervisor workflow."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from trustworthy_assistant.supervisor.models import GateStatus, VerificationResult


@dataclass
class GateRegistry:
    """Registry for verification gate functions."""

    _gates: dict[str, Callable[[], VerificationResult]] = field(default_factory=dict)

    def register(self, name: str, gate_fn: Callable[[], VerificationResult]) -> None:
        self._gates[name] = gate_fn

    def run(self, name: str) -> VerificationResult:
        if name not in self._gates:
            return VerificationResult(
                gate_name=name,
                status=GateStatus.SKIPPED,
                details=f"Gate '{name}' not found in registry",
            )
        return self._gates[name]()

    def list_gates(self) -> list[str]:
        return list(self._gates.keys())


# Global registry instance
GATE_REGISTRY = GateRegistry()


def run_unit_test_gate() -> VerificationResult:
    """Placeholder for unit test gate."""
    start = time.time()
    return VerificationResult(
        gate_name="unit_test",
        status=GateStatus.SKIPPED,
        duration_ms=int((time.time() - start) * 1000),
        details="Unit test gate not yet wired - requires test runner integration",
    )


def run_replay_gate() -> VerificationResult:
    """Placeholder for replay test gate."""
    start = time.time()
    return VerificationResult(
        gate_name="replay",
        status=GateStatus.SKIPPED,
        duration_ms=int((time.time() - start) * 1000),
        details="Replay gate not yet wired - requires replay harness integration",
    )


def run_benchmark_gate() -> VerificationResult:
    """Placeholder for benchmark gate."""
    start = time.time()
    return VerificationResult(
        gate_name="benchmark",
        status=GateStatus.SKIPPED,
        duration_ms=int((time.time() - start) * 1000),
        details="Benchmark gate not yet wired - requires benchmark suite integration",
    )


def _new_id() -> str:
    return f"vr_{uuid.uuid4().hex[:12]}"


def run_gate_result(
    gate_name: str,
    status: GateStatus,
    duration_ms: int = 0,
    details: str = "",
    metrics: dict[str, Any] | None = None,
) -> VerificationResult:
    """Create a verification result with consistent ID format."""
    return VerificationResult(
        gate_name=gate_name,
        status=status,
        duration_ms=duration_ms,
        details=details,
        metrics=metrics or {},
    )


def aggregate_gate_results(results: list[VerificationResult]) -> dict[str, Any]:
    """Aggregate multiple verification results into a summary."""
    total = len(results)
    passed = sum(1 for r in results if r.status == GateStatus.PASSED)
    failed = sum(1 for r in results if r.status == GateStatus.FAILED)
    skipped = sum(1 for r in results if r.status == GateStatus.SKIPPED)

    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "all_passed": failed == 0 and passed > 0,
        "any_failed": failed > 0,
    }


def register_default_gates() -> None:
    """Register the default verification gates."""
    GATE_REGISTRY.register("unit_test", run_unit_test_gate)
    GATE_REGISTRY.register("replay", run_replay_gate)
    GATE_REGISTRY.register("benchmark", run_benchmark_gate)
