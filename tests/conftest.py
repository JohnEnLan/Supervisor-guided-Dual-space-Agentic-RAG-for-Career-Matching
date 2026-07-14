from __future__ import annotations

import os


# Test collection imports application modules. Disable dotenv before those
# imports and override provider credentials so a developer's real environment
# can never be selected by setdefault or by pydantic-settings.
os.environ["CAREER_RAG_ENV_FILE"] = ""
os.environ["DATABASE_URL"] = "postgresql://test:test@localhost:5432/test"
os.environ["DEEPSEEK_API_KEY"] = "sk-test"
os.environ["QWEN_API_KEY"] = "sk-test"
