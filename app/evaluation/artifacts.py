from __future__ import annotations

import hashlib
from pathlib import Path


def normalized_text_sha256(path: Path) -> str:
    """Hash text bytes after normalizing CRLF and CR line endings to LF."""
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()
