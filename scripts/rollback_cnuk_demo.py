"""Reverse the W5 CN/UK demo-corpus visibility cutover."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.cutover_cnuk_demo import main


if __name__ == "__main__":
    main(default_direction="rollback")
