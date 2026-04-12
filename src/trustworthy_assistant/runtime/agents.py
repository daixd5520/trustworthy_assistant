from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentProfile:
    agent_id: str
    name: str
    personality: str
    channel_hint: str = "terminal"
    prompt_mode: str = "full"
    model_override: str = ""


class AgentRegistry:
    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}
        self._default_agent_id = "main"
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        self.register(
            AgentProfile(
                agent_id="main",
                name="Yanzi",
                personality="A reliable personal AI assistant with governed memory and strong engineering discipline.",
            )
        )
        self.register(
            AgentProfile(
                agent_id="planner",
                name="Planner",
                personality="A structured planning agent focused on sequencing, scope control, and execution plans.",
                prompt_mode="minimal",
            )
        )
        self.register(
            AgentProfile(
                agent_id="reviewer",
                name="Reviewer",
                personality="A careful review agent that emphasizes verification, edge cases, and evidence-backed conclusions.",
                prompt_mode="minimal",
            )
        )

    def register(self, profile: AgentProfile) -> None:
        self._profiles[profile.agent_id] = profile

    def list_profiles(self) -> list[AgentProfile]:
        return list(self._profiles.values())

    def get(self, agent_id: str) -> AgentProfile:
        return self._profiles.get(agent_id, self._profiles[self._default_agent_id])

    @property
    def default_agent_id(self) -> str:
        return self._default_agent_id
