from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, UploadFile


ALLOWED_RESUME_SUFFIXES = {".pdf", ".docx", ".txt"}
MAX_RESUME_UPLOAD_BYTES = 10 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 64 * 1024


async def read_resume_upload(
    file: UploadFile,
    *,
    allowed_suffixes: set[str] | None = None,
    max_upload_bytes: int | None = None,
    chunk_bytes: int | None = None,
) -> tuple[str, str, bytes]:
    """B2 上传确认流：文件流式读入内存缓冲（不落磁盘），返回
    (原始文件名, 归一化后缀, 字节)。非白名单后缀 415（不再伪装 .txt）；
    超过 10MB 413（原 persist_upload 闸门语义在此保留）。"""
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

    filename = (file.filename or "resume").strip() or "resume"
    suffix = Path(filename).suffix.lower()
    if suffix not in resolved_allowed_suffixes:
        await file.close()
        raise HTTPException(status_code=415, detail="unsupported_file_type")

    buffer = bytearray()
    try:
        while chunk := await file.read(resolved_chunk_bytes):
            buffer.extend(chunk)
            if len(buffer) > resolved_max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="resume file exceeds upload size limit",
                )
    finally:
        await file.close()
    return filename, suffix, bytes(buffer)
