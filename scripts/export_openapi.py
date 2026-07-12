from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.v1.router import router


DEFAULT_OUTPUT = Path("tests/snapshots/openapi_v1.json")


def build_openapi_v1() -> dict[str, Any]:
    public_app = FastAPI(title="Career-RAG")
    public_app.include_router(router)
    schema = public_app.openapi()
    return {
        "openapi": schema["openapi"],
        "info": schema["info"],
        "paths": {
            path: value
            for path, value in schema["paths"].items()
            if path.startswith("/api/v1/")
        },
        "components": schema.get("components", {}),
    }


def export_openapi(output: Path = DEFAULT_OUTPUT) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(build_openapi_v1(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the public v1 OpenAPI snapshot")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    export_openapi(args.output)


if __name__ == "__main__":
    main()
