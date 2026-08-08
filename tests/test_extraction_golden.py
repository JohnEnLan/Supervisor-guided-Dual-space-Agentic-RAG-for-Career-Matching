"""B4 逐字节等价线守卫（golden 冻结，方案细化 M2a / Codex 一轮 M2）。

golden.json 由重构前的实现（HEAD=ff14e0f 后、页级重构前）生成——
tests/fixtures/extraction_golden/ 下的输入文件与期望输出一起入库。
页级重构（M2a）与 RESUME_OCR_ENABLED=false 回退线都必须让本测试保持
全绿：任何拼接分隔符/空页过滤/strip/编码 fallback 的行为漂移在此逐字节
炸出。禁止用新实现重新生成 golden 来"修"本测试（自证循环）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "extraction_golden"
MANIFEST = json.loads((FIXTURES / "golden.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("entry", MANIFEST, ids=[e["file"] for e in MANIFEST])
def test_bytes_extraction_matches_frozen_golden(entry: dict) -> None:
    from app.normalization.resume_intake import extract_resume_text_from_bytes

    content = (FIXTURES / entry["file"]).read_bytes()
    text, pages = extract_resume_text_from_bytes(content, entry["suffix"])
    assert text == entry["text"]
    assert pages == entry["pages"]


@pytest.mark.parametrize("entry", MANIFEST, ids=[e["file"] for e in MANIFEST])
def test_path_extraction_matches_frozen_golden(entry: dict) -> None:
    from app.normalization.resume_intake import extract_resume_text

    text, pages = extract_resume_text(FIXTURES / entry["file"])
    assert text == entry["text"]
    assert pages == entry["pages"]


def test_golden_covers_the_required_equivalence_surfaces() -> None:
    files = {entry["file"] for entry in MANIFEST}
    # 双侧一轮点名的覆盖面：空页/间隔空页、DOCX 表格、BOM、GBK、解码兜底
    assert {
        "multi_blank.pdf",
        "all_blank.pdf",
        "single.pdf",
        "table.docx",
        "bom.txt",
        "gbk.txt",
        "fallback.txt",
    } <= files
    by_name = {entry["file"]: entry for entry in MANIFEST}
    # 空页语义：全空 PDF 输出空串但页数保留
    assert by_name["all_blank.pdf"]["text"] == ""
    assert by_name["all_blank.pdf"]["pages"] == 2
    # 间隔空页：只有非空页带 [Page N] 标记，且保留原始页号
    assert "[Page 1]" in by_name["multi_blank.pdf"]["text"]
    assert "[Page 2]" not in by_name["multi_blank.pdf"]["text"]
    assert "[Page 3]" in by_name["multi_blank.pdf"]["text"]
    assert all(entry["path_entry_matches"] for entry in MANIFEST)
