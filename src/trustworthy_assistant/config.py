from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class AppConfig:
    root_dir: Path
    workspace_dir: Path
    benchmark_dir: Path
    model_id: str
    anthropic_api_key: str
    anthropic_base_url: str | None
    max_file_chars: int = 20_000
    max_total_chars: int = 150_000
    max_skills: int = 150
    max_skills_prompt: int = 30_000
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    embedding_model: str = "text-embedding-3-small"
    chroma_persist_dir: str | None = None
    wecom_corp_id: str | None = None
    wecom_agent_id: str | None = None
    wecom_secret: str | None = None

    @property
    def bootstrap_files(self) -> list[str]:
        return [
            "SOUL.md",
            "IDENTITY.md",
            "TOOLS.md",
            "USER.md",
            "HEARTBEAT.md",
            "BOOTSTRAP.md",
            "AGENTS.md",
            "MEMORY.md",
        ]


def load_config(root_dir: Path | None = None) -> AppConfig:
    # In the packaged layout, this file lives under src/trustworthy_assistant/.
    root = root_dir or Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env", override=True)
    return AppConfig(
        root_dir=root,
        workspace_dir=root / "workspace",
        benchmark_dir=root / "workspace" / "benchmarks",
        model_id=os.getenv("MODEL_ID", "claude-sonnet-4-20250514"),
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_base_url=os.getenv("OPENAI_BASE_URL"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        chroma_persist_dir=os.getenv("CHROMA_PERSIST_DIR"),
        wecom_corp_id=os.getenv("WECOM_CORP_ID"),
        wecom_agent_id=os.getenv("WECOM_AGENT_ID"),
        wecom_secret=os.getenv("WECOM_SECRET"),
    )
