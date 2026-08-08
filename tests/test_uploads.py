"""B2 上传确认流：read_resume_upload 的内存缓冲、415/413 闸门契约。"""
import pytest
from fastapi import HTTPException

from app.api.uploads import read_resume_upload


class _FakeUploadFile:
    def __init__(self, filename: str, content: bytes, chunk: int = 7):
        self.filename = filename
        self._content = content
        self._offset = 0
        self._chunk = chunk
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        step = min(size if size > 0 else self._chunk, self._chunk)
        piece = self._content[self._offset : self._offset + step]
        self._offset += len(piece)
        return piece

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_read_resume_upload_buffers_in_memory_and_normalizes_suffix():
    file = _FakeUploadFile("My Resume.PDF", b"pdf-bytes-here")

    filename, suffix, content = await read_resume_upload(file)

    assert filename == "My Resume.PDF"
    assert suffix == ".pdf"
    assert content == b"pdf-bytes-here"
    assert file.closed


@pytest.mark.asyncio
async def test_read_resume_upload_rejects_non_whitelist_suffix_with_415(monkeypatch):
    from app.api import uploads

    monkeypatch.setattr(uploads.settings, "resume_ocr_enabled", False)
    file = _FakeUploadFile("shot.png", b"\x89PNG")

    with pytest.raises(HTTPException) as excinfo:
        await read_resume_upload(file)

    # 不再伪装成 .txt 硬吃（旧行为），显式 415 稳定契约
    assert excinfo.value.status_code == 415
    assert excinfo.value.detail == "unsupported_file_type"
    assert file.closed


@pytest.mark.asyncio
async def test_read_resume_upload_streams_and_rejects_oversize_with_413():
    file = _FakeUploadFile("big.txt", b"x" * 64)

    with pytest.raises(HTTPException) as excinfo:
        await read_resume_upload(file, max_upload_bytes=32, chunk_bytes=8)

    assert excinfo.value.status_code == 413
    assert file.closed
