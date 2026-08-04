import hashlib
import io

import pytest
from fastapi import HTTPException, UploadFile


@pytest.mark.asyncio
async def test_persist_upload_uses_full_session_hash_and_unique_upload_id(
    monkeypatch,
    tmp_path,
):
    from app.api import uploads

    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)

    first = await uploads.persist_upload(
        "a/b",
        UploadFile(file=io.BytesIO(b"first"), filename="resume.txt"),
    )
    collision = await uploads.persist_upload(
        "a_b",
        UploadFile(file=io.BytesIO(b"second"), filename="resume.txt"),
    )
    retransmit = await uploads.persist_upload(
        "a/b",
        UploadFile(file=io.BytesIO(b"third"), filename="resume.txt"),
    )

    first_hash = hashlib.sha256(b"a/b").hexdigest()
    collision_hash = hashlib.sha256(b"a_b").hexdigest()
    assert first.name.startswith(f"{first_hash}-")
    assert collision.name.startswith(f"{collision_hash}-")
    assert len({first.name, collision.name, retransmit.name}) == 3
    assert first.read_bytes() == b"first"
    assert collision.read_bytes() == b"second"
    assert retransmit.read_bytes() == b"third"


@pytest.mark.asyncio
async def test_persist_upload_streams_and_removes_oversize_partial(
    monkeypatch,
    tmp_path,
):
    from app.api import uploads

    class TrackingUpload:
        filename = "resume.pdf"

        def __init__(self):
            self.content = io.BytesIO(b"123456")
            self.read_sizes = []
            self.closed = False

        async def read(self, size=-1):
            self.read_sizes.append(size)
            return self.content.read(size)

        async def close(self):
            self.closed = True

    upload = TrackingUpload()
    monkeypatch.setattr(uploads, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(uploads, "MAX_RESUME_UPLOAD_BYTES", 5)
    monkeypatch.setattr(uploads, "UPLOAD_CHUNK_BYTES", 4)

    with pytest.raises(HTTPException) as exc_info:
        await uploads.persist_upload("session-1", upload)

    assert exc_info.value.status_code == 413
    assert upload.read_sizes and set(upload.read_sizes) == {4}
    assert upload.closed is True
    assert list(tmp_path.iterdir()) == []
