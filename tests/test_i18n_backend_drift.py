from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_backend_i18n_dictionary_matches_backend_sources() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_i18n_backend_drift.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_backend_i18n_dictionary_reports_drift_for_explicit_paths(tmp_path: Path) -> None:
    app_root = tmp_path / "app"
    (app_root / "api" / "v1").mkdir(parents=True)
    (app_root / "api" / "conversation_projector.py").write_text(
        'MESSAGE = "matching backend key"\n', encoding="utf-8"
    )
    (app_root / "api" / "v1" / "sessions.py").write_text(
        'MESSAGE = "another backend key"\n', encoding="utf-8"
    )
    en_path = tmp_path / "en.ts"
    drifted_key = "drifted backend key"
    en_path.write_text(
        "\n".join(
            [
                "export const EN_TRANSLATIONS = {",
                "// BACKEND_SOURCE_KEYS_START",
                f'  "{drifted_key}": "Drifted backend key",',
                "// BACKEND_SOURCE_KEYS_END",
                "};",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/check_i18n_backend_drift.py",
            "--en-path",
            str(en_path),
            "--app-root",
            str(app_root),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert drifted_key in result.stderr
