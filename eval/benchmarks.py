from dataclasses import dataclass
from pathlib import Path

from trustworthy_assistant.eval.replay import ReplayHarness, ReplayStep


@dataclass(frozen=True, slots=True)
class BenchmarkScenario:
    name: str
    description: str
    steps: list[ReplayStep]


class BenchmarkSuite:
    def __init__(self) -> None:
        self.scenarios = [
            BenchmarkScenario(
                name="governed_preference_flow",
                description="Write stable preference, recall it, and keep projection in sync.",
                steps=[
                    ReplayStep(action="write", content="以后都用中文回答。", category="preference"),
                    ReplayStep(action="search", query="中文回答"),
                    ReplayStep(action="sync"),
                ],
            ),
            BenchmarkScenario(
                name="candidate_review_flow",
                description="Create a candidate memory and resolve it through manual review.",
                steps=[
                    ReplayStep(action="ingest", content="请用中文回答"),
                    ReplayStep(action="confirm"),
                    ReplayStep(action="search", query="中文回答"),
                ],
            ),
            BenchmarkScenario(
                name="candidate_rejection_flow",
                description="Reject a candidate and ensure it no longer remains pending.",
                steps=[
                    ReplayStep(action="ingest", content="请用中文回答"),
                    ReplayStep(action="reject"),
                ],
            ),
        ]

    def list_scenarios(self) -> list[BenchmarkScenario]:
        return list(self.scenarios)

    def run_all(self, workspace_root: Path) -> list[dict]:
        reports = []
        for scenario in self.scenarios:
            scenario_dir = workspace_root / scenario.name
            harness = ReplayHarness(scenario_dir)
            report = harness.run(scenario.steps)
            reports.append(
                {
                    "name": scenario.name,
                    "description": scenario.description,
                    "report": report.to_dict(),
                    "text": report.render_text(),
                }
            )
        return reports
