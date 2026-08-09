"""Check marked deterministic backend messages against their Python sources."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path


BACKEND_SOURCE_FILES = (
    Path("api/conversation_projector.py"),
    Path("api/v1/sessions.py"),
)
SECTION_START = "// BACKEND_SOURCE_KEYS_START"
SECTION_END = "// BACKEND_SOURCE_KEYS_END"
KEY_PATTERN = re.compile(r'^\s*"((?:\\.|[^"\\])*)"\s*:', re.MULTILINE)


def marked_backend_keys(en_path: Path) -> list[str]:
    """Return only keys inside the explicit backend-source section."""
    content = en_path.read_text(encoding="utf-8")
    start = content.find(SECTION_START)
    end = content.find(SECTION_END)
    if start == -1 or end == -1 or end <= start:
        raise ValueError("backend-source key section is missing or malformed")
    if content.find(SECTION_START, start + 1) != -1:
        raise ValueError("backend-source key section start marker appears more than once")
    if content.find(SECTION_END, end + 1) != -1:
        raise ValueError("backend-source key section end marker appears more than once")

    section = content[start + len(SECTION_START) : end]
    keys = [json.loads(f'"{match.group(1)}"') for match in KEY_PATTERN.finditer(section)]
    if not keys:
        raise ValueError("backend-source key section contains no keys")
    return keys


def source_string_constants(app_root: Path) -> set[str]:
    """Collect exact Python string constants from the two approved backend sources."""
    constants: set[str] = set()
    for relative_path in BACKEND_SOURCE_FILES:
        source_path = app_root / relative_path
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        constants.update(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    return constants


def check_backend_i18n(en_path: Path, app_root: Path) -> list[str]:
    source_constants = source_string_constants(app_root)
    return [
        key
        for key in marked_backend_keys(en_path)
        if key not in source_constants
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Detect drift in marked deterministic backend i18n keys."
    )
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--en-path", type=Path, default=root / "frontend/src/i18n/en.ts")
    parser.add_argument("--app-root", type=Path, default=root / "app")
    args = parser.parse_args()

    try:
        missing_keys = check_backend_i18n(args.en_path, args.app_root)
    except (OSError, SyntaxError, ValueError) as error:
        print(f"backend i18n drift check failed: {error}", file=sys.stderr)
        return 1

    if missing_keys:
        print("Backend i18n drift detected:", file=sys.stderr)
        for key in missing_keys:
            print(f"- {key}", file=sys.stderr)
        return 1

    print("Backend i18n deterministic keys are in sync.")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
