from __future__ import annotations

import hashlib


def test_normalized_text_sha256_is_stable_across_line_endings(tmp_path):
    from app.evaluation.artifacts import normalized_text_sha256

    expected = hashlib.sha256(b"header\nfirst\nsecond\n").hexdigest()
    variants = {
        "lf.txt": b"header\nfirst\nsecond\n",
        "crlf.txt": b"header\r\nfirst\r\nsecond\r\n",
        "mixed.txt": b"header\r\nfirst\nsecond\r\n",
    }

    for name, content in variants.items():
        path = tmp_path / name
        path.write_bytes(content)
        assert normalized_text_sha256(path) == expected
