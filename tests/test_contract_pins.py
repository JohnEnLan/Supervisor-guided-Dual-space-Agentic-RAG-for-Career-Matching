"""B3 契约钉死快照测试（v3 方案 §3.1）。

补齐方案头部锚点表声明的缺失权威：把散落在 prompt 文本与 DTO 注解里的
跨模块契约（咨询 role_clusters 词表全集、phase 四值枚举、120/80 上限）
钉成显式断言——任何一侧单方面改动都会在这里炸出来，而不是静默漂移。
存活子串（PHASE_C2 开头等五条）已由 test_consult_engine.py 钉死，此处
不重复。
"""

from __future__ import annotations

import re
from typing import get_args

from annotated_types import MaxLen

from app.agents.consult_engine import (
    CONSULT_PROMPT,
    ConsultPhase,
    _ConsultLLMResponse,
)
from app.api.v1.schemas import (
    ConsultResponse,
    ConsultStateResponse,
    ConsultTranscriptEntry,
)


# 咨询词表全集（NO 'other'——检索侧聚类可有 other，咨询 prompt 词表不含）
CONSULT_ROLE_CLUSTER_VOCAB = {
    "software_engineering",
    "data_ai",
    "product_management",
    "marketing_sales",
    "healthcare",
    "legal",
    "education",
    "operations",
    "finance",
    "customer_support",
}

PHASE_ENUM = {"template", "resume_clarify", "deepen", "explore"}


def test_consult_prompt_role_cluster_vocabulary_is_exactly_pinned() -> None:
    match = re.search(
        r"fixed vocabulary: ([a-z_,\s]+?)\. Map", CONSULT_PROMPT
    )
    assert match is not None, "vocabulary sentence missing from CONSULT_PROMPT"
    vocabulary = {item.strip() for item in match.group(1).split(",")}
    assert vocabulary == CONSULT_ROLE_CLUSTER_VOCAB


def test_consult_phase_enum_is_exactly_four_values_everywhere() -> None:
    assert set(get_args(ConsultPhase)) == PHASE_ENUM
    for model in (ConsultTranscriptEntry, ConsultResponse, ConsultStateResponse):
        annotation = model.model_fields["phase"].annotation
        assert set(get_args(annotation)) == PHASE_ENUM, model.__name__


def _max_len(model: type, field: str) -> int:
    constraints = [
        meta.max_length
        for meta in model.model_fields[field].metadata
        if isinstance(meta, MaxLen)
    ]
    assert constraints, f"{model.__name__}.{field} has no MaxLen constraint"
    return constraints[0]


def test_consult_reply_and_question_length_limits_are_120_and_80() -> None:
    for model in (_ConsultLLMResponse, ConsultTranscriptEntry, ConsultResponse):
        assert _max_len(model, "assistant_reply") == 120, model.__name__
        assert _max_len(model, "next_question") == 80, model.__name__
    assert "max 120 Chinese characters" in CONSULT_PROMPT
    assert "question max 80 Chinese characters" in CONSULT_PROMPT
