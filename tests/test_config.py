import os
import sys
from pathlib import Path

import pytest

from english_coach.config import (
    AppPaths, Config, ConfigError, DEFAULT_MODEL, load_config, save_api_key, save_config,
)
from english_coach.profile import Profile


def _paths(tmp_path) -> AppPaths:
    return AppPaths(tmp_path / "cfg")


def test_app_paths_layout(tmp_path):
    p = _paths(tmp_path)
    assert p.config_file == tmp_path / "cfg" / "config.toml"
    assert p.secrets_file == tmp_path / "cfg" / "secrets.toml"
    assert p.lock_file == tmp_path / "cfg" / "run.lock"
    assert p.log_file == tmp_path / "cfg" / "logs" / "coach.log"
    assert p.last_run_file == tmp_path / "cfg" / "last_run.json"
    assert p.workdir == tmp_path / "cfg" / "workdir"


def test_app_paths_env_override(tmp_path):
    assert AppPaths.default({"ENGLISH_COACH_CONFIG_DIR": str(tmp_path)}).config_dir == tmp_path


def test_app_paths_env_override_relative_becomes_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = AppPaths.default({"ENGLISH_COACH_CONFIG_DIR": "relcfg"})
    assert result.config_dir.is_absolute()
    assert result.config_dir == (tmp_path / "relcfg").resolve()


def test_save_then_load_round_trip(tmp_path):
    p = _paths(tmp_path)
    cfg = Config(vault_path=tmp_path / "vault", timezone="Europe/Berlin", backend="api",
                 schedule_time="06:30", profile=Profile("Spanish", "tester"), max_active=8)
    save_config(p, cfg)
    loaded = load_config(p, env={})
    assert loaded == cfg


def test_defaults(tmp_path):
    p = _paths(tmp_path)
    p.config_dir.mkdir(parents=True)
    p.config_file.write_text('vault_path = "~/v"\n', encoding="utf-8")
    cfg = load_config(p, env={})
    assert cfg.vault_path == Path.home() / "v"
    assert cfg.backend == "cli" and cfg.model == DEFAULT_MODEL
    assert cfg.profile == Profile()
    assert (cfg.max_active, cfg.max_new_phrases, cfg.adopted_threshold) == (12, 2, 3)


def test_missing_config_tells_user_to_init(tmp_path):
    with pytest.raises(ConfigError, match="english-coach init"):
        load_config(_paths(tmp_path), env={})


def test_invalid_toml_names_the_file(tmp_path):
    p = _paths(tmp_path)
    p.config_dir.mkdir(parents=True)
    p.config_file.write_text("vault_path = \n", encoding="utf-8")
    with pytest.raises(ConfigError, match="config.toml"):
        load_config(p, env={})


def test_invalid_backend_rejected(tmp_path):
    p = _paths(tmp_path)
    p.config_dir.mkdir(parents=True)
    p.config_file.write_text('vault_path = "v"\nbackend = "gpt"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="backend"):
        load_config(p, env={})


def test_api_key_env_wins_over_secrets_file(tmp_path):
    p = _paths(tmp_path)
    save_config(p, Config(vault_path=tmp_path))
    save_api_key(p, "sk-ant-file")
    assert load_config(p, env={}).anthropic_api_key == "sk-ant-file"
    assert load_config(p, env={"ANTHROPIC_API_KEY": "sk-ant-env"}).anthropic_api_key == "sk-ant-env"


def test_api_key_not_in_repr_or_config_file(tmp_path):
    p = _paths(tmp_path)
    save_config(p, Config(vault_path=tmp_path, anthropic_api_key="sk-ant-secret"))
    assert "sk-ant-secret" not in p.config_file.read_text(encoding="utf-8")
    assert "sk-ant-secret" not in repr(Config(vault_path=tmp_path, anthropic_api_key="sk-ant-secret"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_secrets_file_is_user_only(tmp_path):
    p = _paths(tmp_path)
    save_api_key(p, "sk-ant-x")
    assert (os.stat(p.secrets_file).st_mode & 0o777) == 0o600


def test_invalid_timezone_rejected_naming_file_and_key(tmp_path):
    paths = AppPaths(tmp_path)
    paths.config_file.write_text('vault_path = "/v"\ntimezone = "Mars/Olympus"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match=r"config\.toml.*timezone"):
        load_config(paths, env={})


@pytest.mark.parametrize("key", ["adopted_threshold", "max_active", "max_new_phrases"])
def test_non_integer_limit_rejected_naming_file_and_key(tmp_path, key):
    paths = AppPaths(tmp_path)
    paths.config_file.write_text(f'vault_path = "/v"\n[limits]\n{key} = "lots"\n',
                                 encoding="utf-8")
    with pytest.raises(ConfigError, match=rf"config\.toml.*limits\.{key}"):
        load_config(paths, env={})
