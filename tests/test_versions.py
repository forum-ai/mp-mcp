"""Every file that carries the release version carries the same one (scripts/bump_version.py)."""
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_manifest_has_the_package_version():
    package = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    manifests = [".claude-plugin/plugin.json", "gemini-extension.json", "plugin.json", ".antigravity-plugin/plugin.json"]
    found = {name: json.loads((ROOT / name).read_text())["version"] for name in manifests}
    assert found == {name: package for name in manifests}


def test_claude_marketplace_entry_sets_no_version():
    marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
    assert all("version" not in entry for entry in marketplace["plugins"])
