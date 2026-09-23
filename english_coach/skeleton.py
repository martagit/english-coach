from __future__ import annotations

import json
import shutil
from importlib.resources import as_file, files
from pathlib import Path

from english_coach import vault as vault_mod

DATAVIEW_VERSION = "0.5.68"
_FOLDERS = ("Daily", "Phrases", "Patterns")


def create_skeleton(vault: Path) -> list[str]:
    vault = Path(vault)
    created: list[str] = []
    for name in _FOLDERS:
        d = vault / name
        if not d.is_dir():
            d.mkdir(parents=True)
            created.append(f"folder {name}/")
    if not (vault / "English Coaching.md").exists():
        vault_mod.write_dashboard(vault)
        created.append("dashboard 'English Coaching.md'")

    obsidian = vault / ".obsidian"
    with as_file(files("english_coach") / "assets" / "obsidian") as src:
        if not obsidian.exists():
            shutil.copytree(src, obsidian)
            created.append(f".obsidian/ with Dataview {DATAVIEW_VERSION}")
            return created
        plugin = obsidian / "plugins" / "dataview"
        if not plugin.exists():
            shutil.copytree(src / "plugins" / "dataview", plugin)
            created.append(f"Dataview {DATAVIEW_VERSION} plugin")
    enabled_file = obsidian / "community-plugins.json"
    enabled = json.loads(enabled_file.read_text(encoding="utf-8")) if enabled_file.exists() else []
    if "dataview" not in enabled:
        enabled.append("dataview")
        enabled_file.write_text(json.dumps(enabled), encoding="utf-8")
        created.append("enabled Dataview")
    return created
