from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs
import tomli_w

from english_coach.profile import Profile

APP_NAME = "english-coach"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_VAULT = Path.home() / "english-coach-vault"
_BACKENDS = ("cli", "api")


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path

    @classmethod
    def default(cls, env: dict | None = None) -> "AppPaths":
        env = os.environ if env is None else env
        override = env.get("ENGLISH_COACH_CONFIG_DIR")
        if override:
            return cls(Path(override).expanduser().resolve())
        return cls(Path(platformdirs.user_config_dir(APP_NAME, appauthor=False, roaming=True)))

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def secrets_file(self) -> Path:
        return self.config_dir / "secrets.toml"

    @property
    def lock_file(self) -> Path:
        return self.config_dir / "run.lock"

    @property
    def log_file(self) -> Path:
        return self.config_dir / "logs" / "coach.log"

    @property
    def last_run_file(self) -> Path:
        return self.config_dir / "last_run.json"

    @property
    def workdir(self) -> Path:
        return self.config_dir / "workdir"


@dataclass(frozen=True)
class Config:
    vault_path: Path
    timezone: str = "UTC"
    backend: str = "cli"
    model: str = DEFAULT_MODEL
    schedule_time: str = "07:00"
    profile: Profile = field(default_factory=Profile)
    adopted_threshold: int = 3
    max_active: int = 12
    max_new_phrases: int = 2
    anthropic_api_key: str = field(default="", repr=False)


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _api_key(paths: AppPaths, env: dict) -> str:
    if env.get("ANTHROPIC_API_KEY"):
        return env["ANTHROPIC_API_KEY"]
    if paths.secrets_file.exists():
        return str(_read_toml(paths.secrets_file).get("ANTHROPIC_API_KEY", ""))
    return ""


def load_config(paths: AppPaths, env: dict) -> Config:
    path = paths.config_file
    if not path.exists():
        raise ConfigError(f"No config at {path}. Run `english-coach init` first.")
    data = _read_toml(path)
    if "vault_path" not in data:
        raise ConfigError(f"{path}: missing 'vault_path'.")
    backend = data.get("backend", "cli")
    if backend not in _BACKENDS:
        raise ConfigError(f"{path}: backend must be one of {_BACKENDS}, got {backend!r}.")
    prof = data.get("profile", {})
    lim = data.get("limits", {})
    return Config(
        vault_path=Path(data["vault_path"]).expanduser(),
        timezone=data.get("timezone", "UTC"),
        backend=backend,
        model=data.get("model", DEFAULT_MODEL),
        schedule_time=data.get("schedule_time", "07:00"),
        profile=Profile(prof.get("native_language", ""),
                        prof.get("context", Profile().context)),
        adopted_threshold=int(lim.get("adopted_threshold", 3)),
        max_active=int(lim.get("max_active", 12)),
        max_new_phrases=int(lim.get("max_new_phrases", 2)),
        anthropic_api_key=_api_key(paths, env),
    )


def save_config(paths: AppPaths, config: Config) -> None:
    data = {
        "vault_path": str(config.vault_path),
        "timezone": config.timezone,
        "backend": config.backend,
        "model": config.model,
        "schedule_time": config.schedule_time,
        "profile": {"native_language": config.profile.native_language,
                    "context": config.profile.context},
        "limits": {"adopted_threshold": config.adopted_threshold,
                   "max_active": config.max_active,
                   "max_new_phrases": config.max_new_phrases},
    }
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_text(tomli_w.dumps(data), encoding="utf-8")


def save_api_key(paths: AppPaths, key: str) -> None:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.secrets_file.write_text(tomli_w.dumps({"ANTHROPIC_API_KEY": key}), encoding="utf-8")
    if sys.platform != "win32":
        os.chmod(paths.secrets_file, 0o600)
