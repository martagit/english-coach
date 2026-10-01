import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from english_coach.skeleton import DATAVIEW_VERSION, create_skeleton


def test_creates_folders_dashboard_and_obsidian(tmp_path):
    v = tmp_path / "vault"
    created = create_skeleton(v)
    for d in ("Daily", "Phrases", "Patterns"):
        assert (v / d).is_dir()
    assert (v / "English Coaching.md").exists()
    manifest = json.loads((v / ".obsidian/plugins/dataview/manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == DATAVIEW_VERSION
    assert json.loads((v / ".obsidian/community-plugins.json").read_text()) == ["dataview"]
    assert created  # reports what it did


def test_existing_notes_and_obsidian_config_are_kept(tmp_path):
    v = tmp_path / "vault"
    (v / "Phrases").mkdir(parents=True)
    (v / "Phrases" / "park it.md").write_text("mine", encoding="utf-8")
    (v / ".obsidian").mkdir()
    (v / ".obsidian" / "app.json").write_text('{"mine": 1}', encoding="utf-8")
    (v / ".obsidian" / "community-plugins.json").write_text('["calendar"]', encoding="utf-8")
    create_skeleton(v)
    assert (v / "Phrases" / "park it.md").read_text(encoding="utf-8") == "mine"
    assert (v / ".obsidian" / "app.json").read_text(encoding="utf-8") == '{"mine": 1}'
    assert json.loads((v / ".obsidian/community-plugins.json").read_text()) == ["calendar", "dataview"]
    assert (v / ".obsidian/plugins/dataview/main.js").exists()


def test_second_run_is_noop(tmp_path):
    v = tmp_path / "vault"
    create_skeleton(v)
    assert create_skeleton(v) == []


@pytest.mark.slow
def test_wheel_contains_obsidian_assets(tmp_path):
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["uv", "build", "--wheel", "--out-dir", str(tmp_path)], cwd=root, check=True)
    wheel = next(tmp_path.glob("*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    for f in ("english_coach/assets/obsidian/plugins/dataview/main.js",
              "english_coach/assets/obsidian/plugins/dataview/manifest.json",
              "english_coach/assets/obsidian/community-plugins.json",
              "english_coach/assets/constructions.toml"):
        assert f in names


def test_skeleton_creates_and_seeds_constructions(tmp_path):
    v = tmp_path / "vault"
    created = create_skeleton(v)
    assert (v / "Constructions" / "be supposed to.md").exists()
    assert "starter grammar constructions" in created
