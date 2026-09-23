from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from english_coach.profile import Profile


@dataclass(frozen=True)
class Config:
    langfuse_host: str
    langfuse_public_key: str
    langfuse_secret_key: str = field(repr=False)
    anthropic_api_key: str = field(repr=False)
    vault_path: Path
    mcp_json_path: Path
    timezone: str = "Europe/Warsaw"
    model: str = "claude-opus-4-8"
    adopted_threshold: int = 3
    max_active: int = 12
    max_new_phrases: int = 2
    profile: Profile = field(default_factory=Profile)


def load_langfuse_creds(mcp_json_path: Path, env: dict) -> tuple[str, str, str]:
    file_env: dict = {}
    path = Path(mcp_json_path)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        file_env = (data.get("mcpServers", {}).get("langfuse", {}).get("env", {})) or {}

    def pick(key: str) -> str:
        return env.get(key) or file_env.get(key) or ""

    host = pick("LANGFUSE_HOST")
    pub = pick("LANGFUSE_PUBLIC_KEY")
    sec = pick("LANGFUSE_SECRET_KEY")
    if not (host and pub and sec):
        raise RuntimeError("Missing Langfuse credentials (host/public/secret).")
    return host, pub, sec


def load_anthropic_key(vault_path: Path, env: dict) -> str:
    secrets_path = Path(vault_path) / ".coach-secrets.json"
    if secrets_path.exists():
        data = json.loads(secrets_path.read_text(encoding="utf-8"))
        key = data.get("ANTHROPIC_API_KEY")
        if key:
            return key
    if env.get("ANTHROPIC_API_KEY"):
        return env["ANTHROPIC_API_KEY"]
    raise RuntimeError(
        f"ANTHROPIC_API_KEY not found in {Path(vault_path) / '.coach-secrets.json'} or environment."
    )


def load_config(vault_path: Path, mcp_json_path: Path, env: dict) -> Config:
    host, pub, sec = load_langfuse_creds(mcp_json_path, env)
    # The Anthropic key is only needed for the API backend; the default Claude
    # Code (CLI) backend authenticates via the local `claude` install. So treat
    # a missing key as empty rather than failing the whole run.
    try:
        key = load_anthropic_key(vault_path, env)
    except RuntimeError:
        key = ""
    return Config(
        langfuse_host=host,
        langfuse_public_key=pub,
        langfuse_secret_key=sec,
        anthropic_api_key=key,
        vault_path=Path(vault_path),
        mcp_json_path=Path(mcp_json_path),
    )
