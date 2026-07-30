# Correct Dual-space RAG Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将当前“岗位库 + 简化标签案例”重构为正确的双 RAG：显式公共 JD 向量库与隐式公共匿名简历结果库，并用延迟、多渠道反馈持续更新隐式空间。

**Architecture:** 显式分支继续执行 SQL 硬过滤、BM25、dense、RRF 与 bi-encoder；隐式分支按匿名简历向量检索历史简历，再根据公司、岗位和最高招聘阶段聚合经验分。两个分支并行检索，在显式候选集内进行置信度受控融合；推荐记录、申请事件、延迟回访和渠道发送全部持久化到 PostgreSQL，微信公众号只作为未来的渠道适配器。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic、asyncio、asyncpg、PostgreSQL、pgvector HNSW、Qwen Embedding、DeepSeek OpenAI-compatible API、pytest。

## Global Constraints

- 双 RAG 的两个空间固定为：公共岗位 JD 空间和公共匿名简历结果空间；用户私有状态不属于双 RAG。
- 原始简历保存在用户私有空间；进入隐式公共空间前只删除姓名、邮箱、电话、地址、证件号、学号和个人主页等身份信息。
- 匿名简历必须保留教育、专业、学校、实习公司、工作公司、岗位、项目、技能和经历描述。
- 推荐、申请、招聘阶段反馈必须是不同事件；推荐完成后不得立即把用户视为已申请。
- 隐式案例只有在用户确认申请且提供明确招聘阶段后才能生成或更新。
- 硬约束继续由 SQL/metadata 执行，隐式分数只能重排当前有效显式候选，不能恢复被硬过滤的岗位。
- 外部 LLM/embedding 调用必须经过现有 Semaphore；并发只使用 asyncio。
- 所有状态、回访计划和发送状态必须持久化到 PostgreSQL，不得使用进程全局变量或跨天 `asyncio.sleep`。
- 旧 `career_cases` 和 `case_soft_preferences` 在迁移期只保留兼容读取，不再代表隐式空间；不得直接删除已有表或用户数据。
- 实际微信公众号 OAuth/模板消息 API 不在本计划范围；本计划交付渠道无关接口、数据库 outbox 和可运行的 console/demo adapter。
- P2 RAPTOR 与 cross-encoder 不进入本次重构主线。
- 每个任务必须遵循 TDD：先写失败测试、确认失败、最小实现、通过测试、独立提交。

## Delivery Order

| 顺序 | 交付物 | 预计工作日 | 验收门槛 |
| --- | --- | ---: | --- |
| 1 | 正确数据契约与非破坏性 schema | 1 | 模型和 schema contract 测试通过 |
| 2 | 简历快照与严格去身份化 | 1 | PII 删除且公司/经历保留 |
| 3 | 匿名案例及招聘结果仓储 | 1 | 同一申请可单调更新招聘阶段 |
| 4 | 隐式检索、关系评分和双空间融合 | 2 | 冷启动不变，案例充足时可解释重排 |
| 5 | Agent/Supervisor 双证据解释 | 1 | JD 证据和历史案例证据分别可追溯 |
| 6 | 推荐跟踪、延迟回访和渠道接口 | 1 | 无立即反馈、可重试、可退订、无重复发送 |
| 7 | 样例、显式/双空间对照评估和全量复验 | 1 | 指标表、覆盖率、并发基准、全套测试通过 |

---

### Task 1: Lock the Correct Domain Contract and Database Schema

**Files:**
- Create: `app/memory/case_schema.py`
- Modify: `app/db/schema.sql`
- Modify: `app/state/schema.py`
- Test: `tests/test_dual_space_schema.py`

**Interfaces:**
- Consumes: existing `ResumeState`, `JobCandidate`, PostgreSQL/pgvector configuration.
- Produces: `HiringStage`, `FinalStatus`, `AnonymousResumeCase`, `CaseJobOutcome`, `ImplicitEvidence`, and durable table contracts used by all later tasks.

- [ ] **Step 1: Write failing model and schema contract tests**

```python
from pathlib import Path


def test_dual_space_schema_declares_required_tables():
    sql = Path("app/db/schema.sql").read_text(encoding="utf-8")
    for table in (
        "resume_snapshots",
        "external_identities",
        "recommendations",
        "application_tracking",
        "feedback_events",
        "feedback_followups",
        "feedback_outbox",
        "anonymous_resume_cases",
        "case_job_outcomes",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql


def test_outcome_stage_is_monotonic():
    from app.memory.case_schema import HiringStage

    assert HiringStage.APPLIED.weight < HiringStage.SCREEN_PASSED.weight
    assert HiringStage.SCREEN_PASSED.weight < HiringStage.OFFER.weight
    assert HiringStage.OFFER.weight < HiringStage.JOINED.weight
```

- [ ] **Step 2: Run the tests and confirm the missing-contract failure**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_dual_space_schema.py -q`

Expected: FAIL because `app.memory.case_schema` and the new table declarations do not exist.

- [ ] **Step 3: Add the shared domain models**

```python
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class HiringStage(StrEnum):
    APPLIED = "applied"
    SCREEN_PASSED = "screen_passed"
    OA_PASSED = "oa_passed"
    INTERVIEW = "interview"
    OFFER = "offer"
    JOINED = "joined"

    @property
    def weight(self) -> float:
        return {
            HiringStage.APPLIED: 0.0,
            HiringStage.SCREEN_PASSED: 0.40,
            HiringStage.OA_PASSED: 0.55,
            HiringStage.INTERVIEW: 0.70,
            HiringStage.OFFER: 0.90,
            HiringStage.JOINED: 1.00,
        }[self]


class FinalStatus(StrEnum):
    ACTIVE = "active"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    OFFER_DECLINED = "offer_declined"
    JOINED = "joined"


class AnonymousResumeCase(BaseModel):
    case_id: str
    resume_payload: dict[str, Any]
    embedding_text: str


class CaseJobOutcome(BaseModel):
    outcome_id: str
    case_id: str
    job_id: str | None = None
    company: str
    role_family: str
    explicit_match_score: float = Field(ge=0.0, le=1.0)
    highest_stage: HiringStage
    final_status: FinalStatus
    source_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ImplicitEvidence(BaseModel):
    job_id: str
    score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    effective_case_count: int = Field(ge=0)
    supporting_cases: list[dict[str, Any]] = Field(default_factory=list)
```

- [ ] **Step 4: Add non-destructive table declarations**

Add `CREATE TABLE IF NOT EXISTS` declarations with these ownership rules:

```sql
CREATE TABLE IF NOT EXISTS resume_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    resume_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS external_identities (
    identity_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    external_subject TEXT NOT NULL,
    consent_status TEXT NOT NULL,
    bound_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    UNIQUE (provider, external_subject)
);

CREATE TABLE IF NOT EXISTS anonymous_resume_cases (
    case_id TEXT PRIMARY KEY,
    resume_payload JSONB NOT NULL,
    embedding_text TEXT NOT NULL,
    embedding vector(1024),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS case_job_outcomes (
    outcome_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL REFERENCES anonymous_resume_cases(case_id),
    job_id TEXT REFERENCES jobs(job_id),
    company TEXT NOT NULL,
    role_family TEXT NOT NULL,
    explicit_match_score DOUBLE PRECISION NOT NULL,
    highest_stage TEXT NOT NULL,
    final_status TEXT NOT NULL,
    source_confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Add the seven private snapshot/identity/tracking/outbox tables named by the test. Their rows may contain `user_id`; the two public implicit tables must not contain `user_id`, email, phone, external account ID, or raw resume text.

- [ ] **Step 5: Add state references without embedding public cases into session state**

Add `resume_version_id: str | None` to `ResumeState`, and add only recommendation/application identifiers to `FeedbackState`. Do not store shared case payloads inside `SharedState`.

- [ ] **Step 6: Run tests and commit**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_dual_space_schema.py tests/test_memory_phase_e.py -q`

Expected: PASS.

Commit: `git commit -m "Define correct dual-space data contracts"`

---

### Task 2: Build Resume Snapshots and Strict PII Anonymization

**Files:**
- Create: `app/memory/anonymization.py`
- Modify: `app/memory/private_memory.py`
- Modify: `app/normalization/resume_intake.py`
- Test: `tests/test_resume_anonymization.py`

**Interfaces:**
- Consumes: `ResumeState` and private `resume_version_id`.
- Produces: `anonymize_resume_state(resume_state: ResumeState) -> AnonymousResumeCase`, `save_resume_snapshot(*, user_id: str, resume_version_id: str, resume_state: ResumeState) -> str`, and canonical embedding text shared by implicit writes and reads.

- [ ] **Step 1: Write failing privacy-boundary tests**

```python
def test_anonymizer_removes_identity_but_preserves_career_evidence():
    from app.memory.anonymization import anonymize_resume_state
    from app.state.schema import ResumeState

    resume = ResumeState(
        experience=[
            {
                "company": "Tencent",
                "title": "Data Analyst Intern",
                "description": "Built SQL dashboards",
            }
        ],
        skills=["SQL", "Python"],
        normalized_base_resume=(
            "Alice Zhang alice@example.com +44 7700 900123 "
            "Tencent Data Analyst Intern, built SQL dashboards"
        ),
    )

    case = anonymize_resume_state(resume)
    serialized = str(case.model_dump())

    assert "Alice Zhang" not in serialized
    assert "alice@example.com" not in serialized
    assert "7700" not in serialized
    assert "Tencent" in serialized
    assert "Data Analyst Intern" in serialized
    assert "SQL" in serialized
```

- [ ] **Step 2: Confirm the test fails**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_resume_anonymization.py -q`

Expected: FAIL because `anonymize_resume_state` is missing.

- [ ] **Step 3: Implement structured anonymization and deterministic case IDs**

Implement these rules in `anonymization.py`:

```python
IDENTITY_KEYS = {
    "name",
    "full_name",
    "email",
    "phone",
    "address",
    "student_id",
    "national_id",
    "linkedin",
    "github",
    "personal_url",
}


def anonymize_resume_state(resume_state: ResumeState) -> AnonymousResumeCase:
    payload = _sanitize_value(resume_state.model_dump(mode="json"))
    payload.pop("original_evidence_spans", None)
    embedding_text = build_anonymous_resume_embedding_text(payload)
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    case_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return AnonymousResumeCase(
        case_id=case_id,
        resume_payload=payload,
        embedding_text=embedding_text,
    )
```

`_sanitize_value` must remove identity keys recursively and redact email, phone, address-like contact lines, personal URLs and ID-number patterns in free text. It must not remove organization names from `education`, `experience`, or `projects`.

- [ ] **Step 4: Save a private immutable snapshot during resume intake**

Use a UUID or content-derived private snapshot identifier. Save the full private `ResumeState` through `private_memory.py`, then set `state.resume_state.resume_version_id` before `save_state`. Do not write the anonymous case at upload time.

- [ ] **Step 5: Run privacy, intake and evidence tests**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_resume_anonymization.py tests/test_resume_intake.py tests/test_memory_phase_e.py -q`

Expected: PASS; existing evidence spans remain available privately.

- [ ] **Step 6: Commit**

Commit: `git commit -m "Add private snapshots and resume anonymization"`

---

### Task 3: Replace Thin Career Tags with Anonymous Resume Cases and Outcomes

**Files:**
- Modify: `app/memory/case_base.py`
- Create: `app/memory/outcome_repository.py`
- Modify: `app/memory/feedback_loop.py`
- Modify: `app/agents/supervisor.py`
- Test: `tests/test_implicit_case_repository.py`
- Test: `tests/test_feedback_loop.py`

**Interfaces:**
- Consumes: private resume snapshot, explicit job score, user-confirmed application event.
- Produces: `upsert_anonymous_resume_case`, `upsert_case_job_outcome`, and monotonic outcome updates.

- [ ] **Step 1: Write failing repository tests**

Test all of the following:

```python
def test_outcome_stage_never_regresses():
    existing = {"highest_stage": "interview", "final_status": "active"}
    incoming = {"highest_stage": "screen_passed", "final_status": "active"}
    merged = merge_outcome_progress(existing, incoming)
    assert merged["highest_stage"] == "interview"


def test_recommendation_without_application_does_not_create_case():
    assert should_publish_implicit_case(
        confirmed_applied=False,
        highest_stage=None,
    ) is False


def test_confirmed_stage_creates_case():
    assert should_publish_implicit_case(
        confirmed_applied=True,
        highest_stage="screen_passed",
    ) is True
```

- [ ] **Step 2: Confirm failures before implementation**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_implicit_case_repository.py tests/test_feedback_loop.py -q`

Expected: new tests fail on missing outcome repository functions.

- [ ] **Step 3: Implement case and outcome upserts**

`case_base.py` must expose:

```python
async def upsert_anonymous_resume_case(
    case: AnonymousResumeCase,
    *,
    embedding: list[float] | None = None,
) -> None:
    vector = embedding or await embed_one(case.embedding_text)
    if len(vector) != settings.embed_dim:
        raise ValueError("anonymous case embedding dimension mismatch")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO anonymous_resume_cases (
                case_id, resume_payload, embedding_text, embedding, updated_at
            )
            VALUES ($1, $2::jsonb, $3, $4::vector, now())
            ON CONFLICT (case_id) DO UPDATE SET
                resume_payload = EXCLUDED.resume_payload,
                embedding_text = EXCLUDED.embedding_text,
                embedding = EXCLUDED.embedding,
                updated_at = now()
            """,
            case.case_id,
            json.dumps(case.resume_payload, ensure_ascii=False),
            case.embedding_text,
            _to_vector_literal(vector),
        )


async def search_similar_resume_cases(
    embedding_text: str,
    *,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    vector = await embed_one(embedding_text)
    if len(vector) != settings.embed_dim:
        raise ValueError("anonymous query embedding dimension mismatch")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.case_id,
                c.resume_payload,
                1 - (c.embedding <=> $1::vector) AS similarity,
                o.outcome_id,
                o.job_id,
                o.company,
                o.role_family,
                o.explicit_match_score,
                o.highest_stage,
                o.final_status,
                o.source_confidence
            FROM anonymous_resume_cases c
            JOIN case_job_outcomes o ON o.case_id = c.case_id
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
            """,
            _to_vector_literal(vector),
            top_k,
        )
    return [dict(row) for row in rows]
```

The implementation must call existing `embed_one`, validate `settings.embed_dim`, use pgvector cosine distance, and select only public anonymous fields plus outcome rows.

`outcome_repository.py` must upsert by stable `outcome_id` and use the maximum `HiringStage.weight`; `JOINED` is terminal, and completed outcomes cannot regress to active.

- [ ] **Step 4: Replace the old closure publication rule**

Remove the use of `CareerCase` skill tags as the main closure output. The closure must load the application’s private snapshot, anonymize it, upsert the anonymous resume case, and upsert the corresponding company/job outcome. Keep old `CareerCase` readers behind a deprecated compatibility function until all callers and seed scripts are migrated.

- [ ] **Step 5: Verify idempotency and concurrent monotonicity**

Add fake transaction interleaving tests proving:

- Same event idempotency key does not duplicate the outcome.
- Concurrent `screen_passed` and `interview` events persist `interview`.
- A successful public case write remains truthful if subsequent private metadata persistence fails.

- [ ] **Step 6: Run tests and commit**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_implicit_case_repository.py tests/test_feedback_loop.py tests/test_api_routes.py -q`

Expected: PASS.

Commit: `git commit -m "Persist anonymous resume outcome cases"`

---

### Task 4: Implement Implicit Retrieval and Outcome Scoring

**Files:**
- Create: `app/retrieval/implicit_search.py`
- Modify: `app/retrieval/hybrid_search.py`
- Test: `tests/test_implicit_search.py`

**Interfaces:**
- Consumes: anonymous resume text, similar case rows, and explicit `JobCandidate` metadata.
- Produces: `search_implicit_evidence(*, anonymized_resume_text: str, candidates: list[JobCandidate], top_k_cases: int = 20) -> dict[str, ImplicitEvidence]` without changing the explicit candidate set.

- [ ] **Step 1: Write failing pure-scoring tests**

```python
def test_implicit_score_uses_similarity_stage_and_explicit_relation():
    rows = [
        {
            "case_id": "case-1",
            "similarity": 0.90,
            "job_id": "job-1",
            "company": "Tencent",
            "role_family": "data",
            "explicit_match_score": 0.80,
            "highest_stage": "offer",
            "source_confidence": 1.0,
        },
        {
            "case_id": "case-2",
            "similarity": 0.80,
            "job_id": "job-1",
            "company": "Tencent",
            "role_family": "data",
            "explicit_match_score": 0.70,
            "highest_stage": "screen_passed",
            "source_confidence": 1.0,
        },
    ]

    evidence = aggregate_implicit_evidence(rows, candidate_job_id="job-1")

    assert 0.0 < evidence.score <= 1.0
    assert evidence.effective_case_count == 2
    assert evidence.supporting_cases[0]["case_id"] == "case-1"
```

- [ ] **Step 2: Confirm scoring tests fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_implicit_search.py -q`

Expected: FAIL because the module is missing.

- [ ] **Step 3: Implement the bounded scoring formula**

Use this exact MVP formula:

```python
weighted_sum = sum(
    row["similarity"]
    * HiringStage(row["highest_stage"]).weight
    * row["explicit_match_score"]
    * row["source_confidence"]
    for row in rows
)
weight_sum = sum(
    row["similarity"] * row["source_confidence"]
    for row in rows
)
score = weighted_sum / weight_sum if weight_sum else 0.0
confidence = min(1.0, len(rows) / settings.implicit_min_cases)
```

Match an outcome to a candidate by exact `job_id` first. If the historical JD is unavailable or closed, fall back to normalized `company + role_family`. Do not use a company-only match.

- [ ] **Step 4: Extend `JobCandidate` metadata without changing explicit ranking**

Add `role_cluster`, `explicit_score`, `implicit_score`, `implicit_confidence`, and `implicit_evidence`. Existing `score` remains the externally sorted final score. Existing explicit-only tests must continue to receive the same ordering and scores when implicit evidence is absent.

- [ ] **Step 5: Test cold start, weak evidence and sufficient evidence**

Required cases:

- Empty case rows return `{}`.
- Fewer than `implicit_min_cases` produce confidence below `1.0`.
- Rejected at application/screen stage does not generate a positive stage weight.
- Closed historical jobs may support the same company and role family but never become returned candidates.

- [ ] **Step 6: Run tests and commit**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_implicit_search.py tests/test_hybrid_search.py -q`

Expected: PASS.

Commit: `git commit -m "Score implicit hiring outcome evidence"`

---

### Task 5: Add Parallel Dual-space Retrieval and Confidence-gated Fusion

**Files:**
- Create: `app/retrieval/dual_space_search.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Test: `tests/test_dual_space_search.py`
- Test: `tests/test_llm_concurrency.py`

**Interfaces:**
- Consumes: explicit hybrid search and implicit similar-case search.
- Produces: `dual_space_search(*, query: str, anonymized_resume_text: str, hard_constraints: dict[str, Any], soft_prefs: dict[str, Any], top_k: int, implicit_enabled: bool = True) -> list[JobCandidate]` with explicit-only fallback.

- [ ] **Step 1: Write failing fusion tests**

```python
def candidate(job_id: str, score: float) -> JobCandidate:
    return JobCandidate(
        job_id=job_id,
        score=score,
        explicit_score=score,
        evidence_span_ids=[],
    )


def fake_explicit(rows: list[JobCandidate]):
    async def search(**kwargs):
        return rows

    return search


def fake_implicit(rows: dict[str, ImplicitEvidence]):
    async def search(**kwargs):
        return rows

    return search


@pytest.mark.asyncio
async def test_cold_start_preserves_explicit_order():
    explicit = [candidate("job-1", 0.9), candidate("job-2", 0.8)]
    result = await dual_space_search(
        query="data analyst",
        anonymized_resume_text="SQL Python Tencent internship",
        hard_constraints={},
        soft_prefs={},
        top_k=2,
        explicit_search=fake_explicit(explicit),
        implicit_search=fake_implicit({}),
    )
    assert [row.job_id for row in result] == ["job-1", "job-2"]


@pytest.mark.asyncio
async def test_confident_implicit_evidence_can_rerank_explicit_candidates():
    explicit = [candidate("job-1", 0.90), candidate("job-2", 0.88)]
    evidence = {
        "job-2": ImplicitEvidence(
            job_id="job-2",
            score=1.0,
            confidence=1.0,
            effective_case_count=4,
            supporting_cases=[{"case_id": "case-1"}],
        )
    }
    result = await dual_space_search(
        query="data analyst",
        anonymized_resume_text="SQL Python Tencent internship",
        hard_constraints={},
        soft_prefs={},
        top_k=2,
        explicit_search=fake_explicit(explicit),
        implicit_search=fake_implicit(evidence),
    )
    assert [row.job_id for row in result] == ["job-2", "job-1"]
```

- [ ] **Step 2: Confirm failures**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_dual_space_search.py -q`

Expected: FAIL because `dual_space_search` is missing.

- [ ] **Step 3: Implement parallel branches and bounded failure handling**

Use `asyncio.gather` for explicit retrieval and similar-case retrieval. Ordinary implicit retrieval failure must log/fallback to explicit candidates; `asyncio.CancelledError` must propagate.

```python
beta = settings.implicit_max_weight * evidence.confidence
final_score = (1.0 - beta) * normalized_explicit + beta * evidence.score
```

Set defaults:

```text
IMPLICIT_MIN_CASES=3
IMPLICIT_MAX_WEIGHT=0.30
IMPLICIT_CASE_TOP_K=20
```

The maximum implicit contribution is therefore 30%; user hard constraints and explicit candidate membership remain authoritative.

- [ ] **Step 4: Prove no candidate leakage**

Add tests showing an implicit outcome for `job-hidden` cannot introduce that job when it is absent from explicit hard-filtered candidates.

- [ ] **Step 5: Prove concurrency and Semaphore boundaries**

Measure that explicit and implicit I/O branches overlap. Verify both embedding calls still pass through the existing Qwen Semaphore and cancellation is not swallowed.

- [ ] **Step 6: Run tests and commit**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_dual_space_search.py tests/test_hybrid_search.py tests/test_llm_concurrency.py -q`

Expected: PASS.

Commit: `git commit -m "Fuse explicit and implicit retrieval"`

---

### Task 6: Wire Dual Evidence into Matching Agent and Supervisor

**Files:**
- Modify: `app/agents/matching_agent.py`
- Modify: `app/agents/supervisor.py`
- Modify: `app/agents/orchestrator.py`
- Modify: `app/state/schema.py`
- Test: `tests/test_agents_phase_c.py`

**Interfaces:**
- Consumes: dual-space `JobCandidate` fields.
- Produces: separate explicit and implicit explanations, provenance, confidence and Supervisor verification records.

- [ ] **Step 1: Write failing explanation-contract tests**

The recommended role must expose:

```python
{
    "job_id": "job-1",
    "explicit_score": 0.82,
    "implicit_score": 0.64,
    "implicit_confidence": 0.75,
    "explicit_explanation": "JD evidence-grounded explanation",
    "implicit_explanation": "Historical similar-case evidence",
    "implicit_evidence": [
        {
            "case_id": "case-1",
            "company": "Tencent",
            "highest_stage": "interview",
            "similarity": 0.88,
        }
    ],
}
```

Assert that no implicit evidence yields `implicit_explanation=None`, not invented prose.

- [ ] **Step 2: Confirm failures**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_agents_phase_c.py -q`

Expected: new explanation-contract tests fail.

- [ ] **Step 3: Switch the default search function to `dual_space_search`**

Build the anonymized resume query from `ResumeState` using Task 2. Keep dependency injection so tests can provide fake explicit/implicit search functions. Remove `merge_case_soft_preferences` from `Supervisor.plan_retrieval`; user-entered soft preferences remain explicit inputs, while historical outcomes affect ranking only through `dual_space_search`.

- [ ] **Step 4: Extend Top-5 explanation prompts safely**

The prompt must separate:

```text
EXPLICIT JD EVIDENCE
ANONYMOUS HISTORICAL OUTCOME EVIDENCE
```

Require historical counts, stages and confidence. Forbid causal or guaranteed language such as “will pass”, “guaranteed”, or “because similar candidates succeeded”. Keep the existing `asyncio.gather`, per-candidate failure isolation, empty-output rejection and Semaphore tests.

- [ ] **Step 5: Add deterministic Supervisor checks**

Supervisor must remove implicit claims when:

- `implicit_confidence == 0`.
- Evidence case IDs are missing.
- The explanation claims more supporting cases than provided.
- The wording promises an outcome.

The bounded repair loop remains maximum one attempt.

- [ ] **Step 6: Run tests and commit**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_agents_phase_c.py tests/test_matching_explanation_benchmark.py -q`

Expected: PASS.

Commit: `git commit -m "Explain dual-space career matches"`

---

### Task 7: Track Recommendations, Applications and Incremental Feedback Events

**Files:**
- Create: `app/memory/application_tracking.py`
- Modify: `app/memory/feedback.py`
- Modify: `app/memory/feedback_loop.py`
- Modify: `app/db/state_store.py`
- Modify: `app/api/routes.py`
- Modify: `app/agents/orchestrator.py`
- Test: `tests/test_application_tracking.py`
- Test: `tests/test_api_routes.py`

**Interfaces:**
- Consumes: completed recommendations and delayed user responses.
- Produces: recommendation rows, application rows, append-only feedback events, and case publication only after confirmed application progress.

- [ ] **Step 1: Write failing lifecycle tests**

Required behavior:

```python
def test_recommendation_is_not_an_application():
    recommendation = RecommendationRecord(job_id="job-1", company="Tencent")
    assert recommendation.application_id is None


def test_no_response_never_becomes_negative_outcome():
    result = apply_feedback_event(application=None, event="no_response")
    assert result.case_should_publish is False
    assert result.final_status is None
```

Also test the single application timeline:

```text
applied -> screen_passed -> interview -> offer -> joined
```

and assert replaying the same idempotency key creates one event.

- [ ] **Step 2: Confirm lifecycle tests fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_application_tracking.py tests/test_api_routes.py -q`

Expected: FAIL on missing tracking interfaces.

- [ ] **Step 3: Persist recommendations after successful matching**

At orchestrator completion, write one recommendation row per returned job with `resume_version_id`, explicit/implicit/final scores and `recommended_at`. Do not create an application or implicit case.

- [ ] **Step 4: Add application and event ingestion APIs**

Add:

```text
POST /applications
POST /applications/{application_id}/events
```

`POST /applications` confirms that a user applied and binds the application to the recommendation and private resume snapshot. The event route accepts `stage`, `final_status`, `reason_category`, `occurred_at`, `source`, and `idempotency_key`.

Keep `POST /feedback` as a backward-compatible adapter that maps old outcomes into the new event service; do not maintain two closure implementations.

- [ ] **Step 5: Publish or update the implicit case from the event service**

Only `confirmed_applied=True` plus a valid stage event may call Task 3. Repeated events update the same `outcome_id`; they do not create duplicate public cases.

- [ ] **Step 6: Run tests and commit**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_application_tracking.py tests/test_api_routes.py tests/test_feedback_loop.py -q`

Expected: PASS.

Commit: `git commit -m "Track delayed application outcomes"`

---

### Task 8: Add Durable Delayed Follow-ups and Channel-neutral Delivery

**Files:**
- Create: `app/integrations/feedback_channels.py`
- Create: `app/memory/followups.py`
- Create: `scripts/run_due_followups.py`
- Modify: `app/config.py`
- Modify: `.env.example`
- Test: `tests/test_followups.py`

**Interfaces:**
- Consumes: recommendation/application rows and external identity bindings.
- Produces: due follow-up claims, outbox messages and a channel adapter interface usable by a future WeChat connector.

- [ ] **Step 1: Write failing scheduling tests**

Test that:

- A recommendation schedules an initial “did you apply?” follow-up after the configured delay.
- A newly recommended user is not contacted immediately.
- Only due and consented rows are claimed.
- `attempt_count` never exceeds `FOLLOWUP_MAX_ATTEMPTS`.
- Opt-out cancels pending follow-ups.
- Two dispatchers cannot send the same outbox row.

- [ ] **Step 2: Confirm failures**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_followups.py -q`

Expected: FAIL on missing follow-up modules.

- [ ] **Step 3: Define the channel protocol and demo adapter**

```python
from typing import Protocol


class FeedbackChannel(Protocol):
    async def send(
        self,
        *,
        external_recipient_id: str,
        message_key: str,
        payload: dict[str, object],
    ) -> str:
        """Return the provider message identifier."""


class ConsoleFeedbackChannel:
    async def send(
        self,
        *,
        external_recipient_id: str,
        message_key: str,
        payload: dict[str, object],
    ) -> str:
        return f"console:{external_recipient_id}:{message_key}"
```

The future WeChat connector must implement this protocol; no WeChat SDK or credential is added now.

- [ ] **Step 4: Implement database-driven claiming and outbox delivery**

Claim due rows in a transaction using `FOR UPDATE SKIP LOCKED`, write an outbox row, commit, then send through the adapter. Persist success/failure and next retry time. Never hold a database lock during network I/O.

- [ ] **Step 5: Add the one-shot dispatcher script**

`scripts/run_due_followups.py` runs one bounded dispatch batch and exits. It must not use an infinite loop. A platform scheduler may invoke it periodically.

Set defaults:

```text
FOLLOWUP_INITIAL_DELAY_DAYS=7
FOLLOWUP_STAGE_DELAY_DAYS=7
FOLLOWUP_MAX_ATTEMPTS=3
FOLLOWUP_BATCH_SIZE=50
```

- [ ] **Step 6: Run tests and commit**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_followups.py tests/test_api_routes.py -q`

Expected: PASS.

Commit: `git commit -m "Schedule delayed feedback follow-ups"`

---

### Task 9: Replace Seed Cases with Anonymous Resume Outcome Fixtures

**Files:**
- Modify: `scripts/seed_cases.py`
- Create: `data/cases/anonymous_resume_cases.jsonl`
- Create: `data/cases/case_job_outcomes.jsonl`
- Test: `tests/test_seed_implicit_cases.py`

**Interfaces:**
- Consumes: Task 2 anonymizer and Task 3 repositories.
- Produces: 10-20 PII-free mechanism-demo cases linked to companies, role families and recruitment stages.

- [ ] **Step 1: Write failing fixture tests**

Assert:

- 10-20 cases exist.
- Every case has education, experience, company evidence, project/skill evidence and embedding text.
- No case contains email, phone, person name field or external identity.
- Every outcome references a case and a known `job_id` or a non-empty company/role family fallback.
- Fixtures cover screen pass, OA, interview, offer, joined and rejection.

- [ ] **Step 2: Confirm fixture tests fail**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_seed_implicit_cases.py -q`

Expected: FAIL because the new fixtures are absent.

- [ ] **Step 3: Create deterministic fictional resume/outcome fixtures**

Use fictional profiles and existing Kaggle job/company metadata. Mark the manifest:

```json
{
  "scope": "mechanism_demo",
  "source": "fictional_anonymous_resume_outcomes",
  "not_for_real_world_success_claims": true
}
```

Do not invent that a real person passed a real company; company labels are demo relations only.

- [ ] **Step 4: Update seeding to use the new repositories**

Support `--no-embed` for local mechanism tests and the normal Qwen embedding path for PostgreSQL demos. Keep old thin case seeding behind `--legacy-thin-cases`; do not run it by default.

- [ ] **Step 5: Run tests and commit**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_seed_implicit_cases.py tests/test_memory_phase_e.py -q`

Expected: PASS.

Commit: `git commit -m "Seed anonymous hiring outcome cases"`

---

### Task 10: Evaluate Explicit-only versus Dual-space Retrieval

**Files:**
- Create: `scripts/evaluate_dual_space.py`
- Create: `data/eval/implicit_case_split.json`
- Modify: `data/eval/evaluation_manifest.json`
- Modify: `app/evaluation/metrics.py`
- Test: `tests/test_dual_space_evaluation.py`

**Interfaces:**
- Consumes: existing 1,000-job corpus, explicit rankings, training-side case fixtures and held-out resume queries.
- Produces: a truthful explicit-only/dual-space metric table plus implicit coverage and company evidence hit rate.

- [ ] **Step 1: Write failing leakage and report tests**

```python
def test_held_out_case_is_excluded_from_implicit_retrieval():
    split = load_case_split(Path("data/eval/implicit_case_split.json"))
    assert set(split["train_case_ids"]).isdisjoint(split["test_case_ids"])


def test_report_contains_explicit_and_dual_runs():
    report = build_dual_space_report(labels, explicit_rankings, dual_rankings)
    assert set(report["runs"]) == {"explicit_only", "dual_space"}
    assert "implicit_coverage" in report
    assert "company_evidence_hit_rate@5" in report
```

- [ ] **Step 2: Confirm failures**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_dual_space_evaluation.py -q`

Expected: FAIL because the split and evaluator are missing.

- [ ] **Step 3: Add a fixed train/test case split**

The test query’s own case and outcomes must never appear in implicit retrieval. Record fixture hashes and the 1,000-job corpus SHA-256 in the manifest.

- [ ] **Step 4: Produce the comparison table**

Required columns:

```text
run | k | cases | precision | recall | mrr | ndcg | implicit_coverage | company_evidence_hit_rate
```

Keep RAPTOR, real hiring probability and real-world company success claims marked `not_evaluated`. Label all implicit results as fictional mechanism-demo results until real consented feedback exists.

- [ ] **Step 5: Run evaluator and tests**

Run: `\.venv\Scripts\python.exe scripts/evaluate_dual_space.py --format table --table-k 5`

Expected: two rows named `explicit_only` and `dual_space`, bounded metrics in `[0, 1]`, and nonzero implicit coverage for seeded queries.

Run: `\.venv\Scripts\python.exe -m pytest tests/test_dual_space_evaluation.py tests/test_metrics.py tests/test_eval_dataset.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

Commit: `git commit -m "Evaluate explicit and dual-space retrieval"`

---

### Task 11: End-to-end Verification, Performance Evidence and Documentation

**Files:**
- Create: `scripts/demo_delayed_feedback_loop.py`
- Modify: `scripts/benchmark_matching_explanations.py`
- Modify: `README.md` if present, otherwise create `docs/dual_space_architecture.md`
- Test: `tests/test_dual_space_end_to_end.py`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: one reproducible cold-start demo, one mature dual-space demo, one delayed-feedback demo and final test/performance evidence.

- [ ] **Step 1: Write the end-to-end acceptance test**

The test must prove this sequence:

```text
upload resume
→ explicit-only recommendation while case library is empty
→ recommendation row exists but no application/case exists
→ due follow-up is dispatched through console adapter
→ user confirms application and screen pass
→ anonymous case/outcome is published
→ second similar resume retrieves implicit evidence
→ final explanation contains separate JD and historical evidence
```

- [ ] **Step 2: Run and confirm the acceptance test initially fails**

Run: `\.venv\Scripts\python.exe -m pytest tests/test_dual_space_end_to_end.py -q`

Expected: FAIL until all integration seams are wired.

- [ ] **Step 3: Add a bounded demo script**

`demo_delayed_feedback_loop.py` must execute one deterministic scenario and exit. It may inject fake clock and console channel dependencies; it must not wait seven real days or require WeChat credentials.

- [ ] **Step 4: Extend the benchmark**

Report:

```text
explicit serial/parallel retrieval latency
implicit retrieval latency
dual-space total latency
Top-5 serial/parallel explanation latency
maximum active LLM calls
maximum active embedding calls
```

Confirm that ordinary implicit failure falls back to explicit results and Semaphore limits remain enforced.

- [ ] **Step 5: Run the complete verification matrix**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe scripts\demo_delayed_feedback_loop.py
.\.venv\Scripts\python.exe scripts\evaluate_dual_space.py --format table --table-k 5
.\.venv\Scripts\python.exe scripts\benchmark_matching_explanations.py --candidates 5 --simulated-latency-ms 300 --semaphore-limit 5 --format table
```

Expected:

- Full suite passes.
- Cold-start output equals explicit-only behavior.
- Mature demo includes traceable implicit evidence.
- Delayed feedback creates no case before confirmed application progress.
- All reported metrics are bounded and correctly labelled.
- Serial/parallel benchmark confirms bounded concurrency.

- [ ] **Step 6: Run independent review and commit**

Review must reject:

- Any remaining claim that private memory is one of the two RAG spaces.
- Public cases containing identity fields.
- Recommendation rows treated as applications.
- No-response treated as rejection.
- Implicit evidence introducing hard-filtered jobs.
- Evaluation leakage between train and held-out cases.
- “Will pass” or guaranteed-outcome explanations.

Commit: `git commit -m "Complete correct dual-space RAG workflow"`

## Migration and Rollback Rules

- Execute this plan on a new branch based on `codex/week3-reoptimization`; recommended branch name: `codex/correct-dual-space-rag`.
- Add new tables before changing readers. Do not rename or drop `career_cases`, `private_memory` or `feedback_memory` in the same release.
- Keep `POST /feedback` as a compatibility adapter until the new application-event API is covered by integration tests.
- Gate the new retrieval path with `DUAL_SPACE_ENABLED`; default false until Tasks 1-6 pass, then true for the mechanism demo.
- When disabled or when no eligible cases exist, results must be byte-for-byte equivalent in ordering and evidence to the explicit-only path, excluding new diagnostic fields.
- A rollback disables `DUAL_SPACE_ENABLED` and the follow-up dispatcher; it does not require deleting new tables.

## Scope Boundary

This plan delivers the thesis mechanism and a channel-neutral delayed-feedback demo. Production WeChat account authorization, template approval, provider credentials, rate limits and deployment scheduler configuration require a separate integration plan after the connector requirements are known. KV cache is not used as durable memory; PostgreSQL and pgvector remain the source of truth.

## Self-review Checklist

- [ ] Every user correction is represented: public JD space, public anonymous resume outcome space, company/stage relations, cold start, delayed feedback and retained internship/company evidence.
- [ ] Private state is described only as operational storage, never as one of the RAG spaces.
- [ ] Every task has exact files, interfaces, failing tests, verification commands and a commit boundary.
- [ ] No task requires real WeChat credentials or a cross-day in-process sleep.
- [ ] Explicit-only fallback, hard-filter authority, privacy, idempotency, monotonic stages and evaluation leakage are all tested.
- [ ] P2 RAPTOR/cross-encoder work remains outside the mainline.
