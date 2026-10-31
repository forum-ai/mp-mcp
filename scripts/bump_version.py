"""Set the release version in every file that carries one.

    python scripts/bump_version.py 0.5.0

The package and each client's plugin manifest carry their own copy of the version, because
each client reads only its own file. This script writes all of them; tests/test_versions.py
fails if they ever disagree.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The Claude marketplace entry (.claude-plugin/marketplace.json) deliberately has no version:
# Claude Code reads it from plugin.json, and setting it in both places is an error.
FILES = {
    "pyproject.toml": r'^(version\s*=\s*")[^"]+(")',
    ".claude-plugin/plugin.json": r'^(\s*"version":\s*")[^"]+(")',
    "gemini-extension.json": r'^(\s*"version":\s*")[^"]+(")',
    "plugin.json": r'^(\s*"version":\s*")[^"]+(")',
    ".antigravity-plugin/plugin.json": r'^(\s*"version":\s*")[^"]+(")',
}


def main(version: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        sys.exit(f"{version!r} is not a version like 0.5.0")
    for name, pattern in FILES.items():
        path = ROOT / name
        text, n = re.subn(pattern, rf"\g<1>{version}\g<2>", path.read_text(), count=1, flags=re.M)
        if n != 1:
            sys.exit(f"no version field found in {name}")
        path.write_text(text)
        print(f"{name}: {version}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
