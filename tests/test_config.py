import json
import pytest
from pathlib import Path
from english_coach.config import load_langfuse_creds, load_anthropic_key, load_config


def _write_mcp(path: Path):
    path.write_text(json.dumps({"mcpServers": {"langfuse": {"env": {
        "LANGFUSE_HOST": "http://localhost:3000",
        "LANGFUSE_PUBLIC_KEY": "pk-lf-x",
        "LANGFUSE_SECRET_KEY": "sk-lf-y",
    }}}}), encoding="utf-8")


def test_load_langfuse_creds_from_mcp(tmp_path):
    mcp = tmp_path / ".mcp.json"
    _write_mcp(mcp)
    host, pub, sec = load_langfuse_creds(mcp, env={})
    assert host == "http://localhost:3000"
    assert pub == "pk-lf-x"
    assert sec == "sk-lf-y"


def test_env_overrides_mcp(tmp_path):
    mcp = tmp_path / ".mcp.json"
    _write_mcp(mcp)
    host, pub, sec = load_langfuse_creds(mcp, env={"LANGFUSE_HOST": "http://other:3000"})
    assert host == "http://other:3000"
    assert pub == "pk-lf-x"


def test_load_anthropic_key_from_vault_secrets(tmp_path):
    (tmp_path / ".coach-secrets.json").write_text(
        json.dumps({"ANTHROPIC_API_KEY": "sk-ant-file"}), encoding="utf-8")
    assert load_anthropic_key(tmp_path, env={}) == "sk-ant-file"


def test_load_anthropic_key_env_fallback(tmp_path):
    assert load_anthropic_key(tmp_path, env={"ANTHROPIC_API_KEY": "sk-ant-env"}) == "sk-ant-env"


def test_load_anthropic_key_missing_raises(tmp_path):
    with pytest.raises(RuntimeError):
        load_anthropic_key(tmp_path, env={})


def test_load_config_composes(tmp_path):
    mcp = tmp_path / ".mcp.json"
    _write_mcp(mcp)
    (tmp_path / ".coach-secrets.json").write_text(
        json.dumps({"ANTHROPIC_API_KEY": "sk-ant-file"}), encoding="utf-8")
    cfg = load_config(vault_path=tmp_path, mcp_json_path=mcp, env={})
    assert cfg.langfuse_host == "http://localhost:3000"
    assert cfg.anthropic_api_key == "sk-ant-file"
    assert cfg.model == "claude-opus-4-8"
    assert cfg.adopted_threshold == 3


def test_load_langfuse_creds_missing_raises(tmp_path):
    mcp = tmp_path / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"langfuse": {"env": {
        "LANGFUSE_HOST": "http://localhost:3000",
        "LANGFUSE_PUBLIC_KEY": "pk-lf-x",
        # secret intentionally missing
    }}}}), encoding="utf-8")
    with pytest.raises(RuntimeError):
        load_langfuse_creds(mcp, env={})


def test_config_repr_redacts_secrets(tmp_path):
    mcp = tmp_path / ".mcp.json"
    _write_mcp(mcp)
    (tmp_path / ".coach-secrets.json").write_text(json.dumps({"ANTHROPIC_API_KEY": "sk-ant-file"}), encoding="utf-8")
    cfg = load_config(vault_path=tmp_path, mcp_json_path=mcp, env={})
    r = repr(cfg)
    assert "sk-ant-file" not in r
    assert "sk-lf-y" not in r


def test_config_has_curation_defaults(tmp_path):
    from english_coach.config import Config
    cfg = Config("h", "p", "s", "ak", tmp_path, tmp_path / ".mcp.json")
    assert cfg.max_active == 12
    assert cfg.max_new_phrases == 2
