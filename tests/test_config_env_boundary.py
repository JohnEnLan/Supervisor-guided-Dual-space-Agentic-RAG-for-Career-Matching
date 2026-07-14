from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_empty_env_file_override_disables_dotenv_loading() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "CAREER_RAG_ENV_FILE": "",
            "DATABASE_URL": "postgresql://test:test@localhost:5432/test",
            "DEEPSEEK_API_KEY": "sk-test-isolated",
            "QWEN_API_KEY": "sk-test-isolated",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.config import Settings; "
                "assert Settings.model_config.get('env_file') is None"
            ),
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
