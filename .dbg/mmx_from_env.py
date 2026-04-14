import os
import subprocess
import sys
from pathlib import Path


def load_env(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    env_file = root / ".env"
    env_vars = load_env(env_file) if env_file.exists() else {}
    child_env = os.environ.copy()
    local_home = root / ".dbg" / "mmx-home"
    local_home.mkdir(parents=True, exist_ok=True)
    child_env["HOME"] = str(local_home)
    child_env["XDG_CONFIG_HOME"] = str(local_home)
    child_env["MINIMAX_API_KEY"] = (
        env_vars.get("MINIMAX_API_KEY")
        or env_vars.get("OPENAI_API_KEY")
        or env_vars.get("ANTHROPIC_API_KEY")
        or child_env.get("MINIMAX_API_KEY", "")
    )
    child_env["MINIMAX_REGION"] = env_vars.get("MINIMAX_REGION") or child_env.get("MINIMAX_REGION") or "cn"
    if not child_env["MINIMAX_API_KEY"]:
        print("Error: No MiniMax API key found in .env or MINIMAX_API_KEY.", file=sys.stderr)
        return 1
    cmd = ["mmx", *sys.argv[1:]]
    completed = subprocess.run(cmd, env=child_env)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
