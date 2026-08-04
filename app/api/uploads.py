from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile


UPLOAD_DIR = Path("data/resumes/uploads")
ALLOWED_RESUME_SUFFIXES = {".pdf", ".docx", ".txt"}
MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 64 * 1024


async def persist_upload(
    session_id: str,
    file: UploadFile,
    *,
    upload_dir: Path | None = None,
    allowed_suffixes: set[str] | None = None,
    max_upload_bytes: int | None = None,
    chunk_bytes: int | None = None,
) -> Path:
    resolved_upload_dir = UPLOAD_DIR if upload_dir is None else upload_dir
    resolved_allowed_suffixes = (
        ALLOWED_RESUME_SUFFIXES
        if allowed_suffixes is None
        else allowed_suffixes
    )
    resolved_max_upload_bytes = (
        MAX_RESUME_UPLOAD_BYTES
        if max_upload_bytes is None
        else max_upload_bytes
    )
    resolved_chunk_bytes = (
        UPLOAD_CHUNK_BYTES if chunk_bytes is None else chunk_bytes
    )

    resolved_upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in resolved_allowed_suffixes:
        suffix = ".txt"

    session_hash = _safe_id(session_id)
    # Keep enough entropy for unique immutable upload paths without pushing
    # deeply nested Windows workspaces over the legacy MAX_PATH boundary.
    upload_id = uuid.uuid4().hex[:16]
    path = resolved_upload_dir / f"{session_hash}-{upload_id}{suffix}"
    total_bytes = 0
    try:
        with path.open("xb") as destination:
            while chunk := await file.read(resolved_chunk_bytes):
                total_bytes += len(chunk)
                if total_bytes > resolved_max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail="resume file exceeds upload size limit",
                    )
                destination.write(chunk)
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


def _safe_id(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
