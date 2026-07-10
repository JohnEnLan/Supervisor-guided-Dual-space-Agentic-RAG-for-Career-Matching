import json
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("DEEPSEEK_API_KEY", "sk-test")
os.environ.setdefault("QWEN_API_KEY", "sk-test")


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return FakeAcquire(self.conn)


class InMemoryMemoryConn:
    def __init__(self):
        self.private_rows = {}
        self.feedback_rows = []
        self.next_feedback_id = 1
        self.clock = 0

    async def execute(self, sql, *args):
        if "INSERT INTO private_memory" not in sql:
            raise AssertionError(sql)
        self.clock += 1
        user_id, resume_version_id, payload_json = args
        self.private_rows[(user_id, resume_version_id)] = {
            "resume_version_id": resume_version_id,
            "payload": json.loads(payload_json),
            "updated_at": self.clock,
        }

    async def fetchrow(self, sql, *args):
        if "INSERT INTO feedback_memory" in sql:
            feedback_id = self.next_feedback_id
            self.next_feedback_id += 1
            self.clock += 1
            user_id, job_id, outcome, reason, user_rating = args
            self.feedback_rows.append(
                {
                    "feedback_id": feedback_id,
                    "user_id": user_id,
                    "job_id": job_id,
                    "outcome": outcome,
                    "reason": reason,
                    "user_rating": user_rating,
                    "created_at": self.clock,
                }
            )
            return {"feedback_id": feedback_id}
        if "FROM private_memory" not in sql:
            raise AssertionError(sql)
        user_id, resume_version_id = args
        row = self.private_rows.get((user_id, resume_version_id))
        if row is None:
            return None
        return {"payload": row["payload"]}

    async def fetch(self, sql, *args):
        if "FROM feedback_memory" in sql:
            user_id, limit = args
            rows = [row for row in self.feedback_rows if row["user_id"] == user_id]
            rows.sort(key=lambda row: row["created_at"], reverse=True)
            return rows[:limit]

        if "FROM private_memory" not in sql:
            raise AssertionError(sql)
        user_id, limit = args
        rows = [
            row
            for (row_user_id, _version_id), row in self.private_rows.items()
            if row_user_id == user_id
        ]
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        if "payload" in sql:
            return rows[:limit]
        return [
            {
                "resume_version_id": row["resume_version_id"],
                "updated_at": row["updated_at"],
            }
            for row in rows[:limit]
        ]


def test_private_resume_payload_keeps_raw_resume_in_private_memory_only():
    from app.memory.private_memory import build_private_resume_payload
    from app.state.schema import ResumeState

    payload = build_private_resume_payload(
        resume_state=ResumeState(
            normalized_base_resume="Normalized analyst resume",
            original_evidence_spans=[{"span_id": "R001", "text": "Raw evidence"}],
        ),
        raw_resume_text="John Example john@example.com raw resume text",
        user_goal_text="Find analyst roles",
    )

    assert payload["raw_resume_text"] == "John Example john@example.com raw resume text"
    assert payload["memory_scope"] == "private"
    assert "case_base" not in payload


@pytest.mark.asyncio
async def test_save_private_resume_memory_upserts_by_user_and_version(monkeypatch):
    from app.memory import private_memory
    from app.state.schema import ResumeState

    calls = []

    class FakeConn:
        async def execute(self, sql, *args):
            calls.append((sql, args))

    async def fake_get_pool():
        return FakePool(FakeConn())

    monkeypatch.setattr(private_memory, "get_pool", fake_get_pool)

    await private_memory.save_private_resume_memory(
        user_id="u1",
        resume_version_id="v1",
        resume_state=ResumeState(normalized_base_resume="base"),
        raw_resume_text="private raw text",
    )

    sql, args = calls[0]
    assert "private_memory" in sql
    assert args[0] == "u1"
    assert args[1] == "v1"
    assert "private raw text" in args[2]


@pytest.mark.asyncio
async def test_private_resume_memory_writes_and_reads_user_history(monkeypatch):
    from app.memory import private_memory
    from app.state.schema import ResumeState

    conn = InMemoryMemoryConn()

    async def fake_get_pool():
        return FakePool(conn)

    monkeypatch.setattr(private_memory, "get_pool", fake_get_pool)

    await private_memory.save_private_resume_memory(
        user_id="u1",
        resume_version_id="v1",
        resume_state=ResumeState(normalized_base_resume="u1 first resume"),
        raw_resume_text="private resume v1",
    )
    await private_memory.save_private_resume_memory(
        user_id="u1",
        resume_version_id="v2",
        resume_state=ResumeState(normalized_base_resume="u1 second resume"),
        raw_resume_text="private resume v2",
    )
    await private_memory.save_private_resume_memory(
        user_id="u2",
        resume_version_id="v1",
        resume_state=ResumeState(normalized_base_resume="u2 resume"),
    )

    loaded = await private_memory.load_private_resume_memory(
        user_id="u1", resume_version_id="v1"
    )
    history = await private_memory.list_private_resume_history(user_id="u1", limit=10)

    assert loaded["resume_state"]["normalized_base_resume"] == "u1 first resume"
    assert [row["resume_version_id"] for row in history] == ["v2", "v1"]
    assert [
        row["payload"]["resume_state"]["normalized_base_resume"] for row in history
    ] == ["u1 second resume", "u1 first resume"]


@pytest.mark.asyncio
async def test_feedback_records_outcomes_and_positive_policy(monkeypatch):
    from app.memory import feedback

    class FakeConn:
        async def fetchrow(self, sql, *args):
            self.args = args
            return {"feedback_id": 7}

    conn = FakeConn()

    async def fake_get_pool():
        return FakePool(conn)

    monkeypatch.setattr(feedback, "get_pool", fake_get_pool)

    assert feedback.is_positive_outcome("interview_1") is True
    assert feedback.is_positive_outcome("rejected") is False

    feedback_id = await feedback.record_application_feedback(
        user_id="u1",
        job_id="job-1",
        outcome="interview_1",
        reason="good screen",
        user_rating=4,
    )

    assert feedback_id == 7
    assert conn.args == ("u1", "job-1", "interview_1", "good screen", 4)


@pytest.mark.asyncio
async def test_feedback_records_and_reads_canonical_application_outcomes(monkeypatch):
    from app.memory import feedback

    conn = InMemoryMemoryConn()

    async def fake_get_pool():
        return FakePool(conn)

    monkeypatch.setattr(feedback, "get_pool", fake_get_pool)

    oa_id = await feedback.record_application_feedback(
        user_id="u1",
        job_id="job-oa",
        outcome=" OA ",
    )
    offer_id = await feedback.record_application_feedback(
        user_id="u1",
        job_id="job-offer",
        outcome="Offer",
        user_rating=5,
    )
    rejected_id = await feedback.record_application_feedback(
        user_id="u1",
        job_id="job-rejected",
        outcome="rejected",
        reason="visa sponsorship unavailable",
        user_rating=2,
    )
    await feedback.record_application_feedback(
        user_id="u2",
        job_id="job-other",
        outcome="offer",
    )

    rows = await feedback.list_feedback_for_user(user_id="u1", limit=10)

    assert (oa_id, offer_id, rejected_id) == (1, 2, 3)
    assert [row["job_id"] for row in rows] == [
        "job-rejected",
        "job-offer",
        "job-oa",
    ]
    assert [row["outcome"] for row in rows] == ["rejected", "offer", "oa"]
    assert rows[0]["reason"] == "visa sponsorship unavailable"


@pytest.mark.asyncio
async def test_state_store_feedback_locks_and_updates_latest_state_atomically(
    monkeypatch,
):
    from app.db import state_store
    from app.state.schema import SharedState

    calls = []
    current_state = SharedState(session_id="s1", user_id="u1")
    current_state.career_state.current_goal = ["newer unrelated goal"]

    class FakeTransaction:
        async def __aenter__(self):
            calls.append("transaction_enter")

        async def __aexit__(self, exc_type, exc, tb):
            calls.append("transaction_exit")
            return False

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

        async def fetchrow(self, sql, *args):
            calls.append(("fetchrow", sql, args))
            if "FROM session_state" in sql:
                return {"state": current_state.model_dump_json()}
            if "INSERT INTO feedback_memory" in sql:
                return {"feedback_id": 9}
            raise AssertionError(sql)

        async def execute(self, sql, *args):
            calls.append(("execute", sql, args))

    conn = FakeConn()

    async def fake_get_pool():
        return FakePool(conn)

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    result = await state_store.add_feedback(
        session_id="s1",
        job_id="job-1",
        outcome="Offer",
    )

    assert result.feedback_id == 9
    assert result.created is True
    assert result.feedback == {
        "job_id": "job-1",
        "outcome": "offer",
        "reason": None,
        "user_rating": None,
        "feedback_id": 9,
    }
    assert calls[0] == "transaction_enter"
    select_sql = calls[1][1]
    feedback_insert_sql, feedback_insert_args = calls[2][1:]
    update_sql, update_args = calls[3][1:]
    assert "FOR UPDATE" in select_sql
    assert "INSERT INTO feedback_memory" in feedback_insert_sql
    assert feedback_insert_args == ("u1", "job-1", "offer", None, None)
    assert "UPDATE session_state" in update_sql
    assert "status" not in update_sql.lower()
    written_state = json.loads(update_args[0])
    assert written_state["career_state"]["current_goal"] == ["newer unrelated goal"]
    assert written_state["feedback_state"]["user_feedback"] == [
        {
            "job_id": "job-1",
            "outcome": "offer",
            "reason": None,
            "user_rating": None,
            "feedback_id": 9,
        }
    ]
    assert calls[4] == "transaction_exit"


@pytest.mark.asyncio
async def test_state_store_feedback_reuses_persisted_idempotency_key(monkeypatch):
    from app.db import state_store
    from app.state.schema import SharedState

    calls = []
    current_state = SharedState(session_id="s1", user_id="u1")
    current_state.feedback_state.user_feedback = [
        {
            "feedback_id": 9,
            "job_id": "job-1",
            "outcome": "offer",
            "idempotency_key": "feedback-request-1",
        }
    ]

    class FakeTransaction:
        async def __aenter__(self):
            calls.append("transaction_enter")

        async def __aexit__(self, exc_type, exc, tb):
            calls.append("transaction_exit")
            return False

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

        async def fetchrow(self, sql, *args):
            calls.append(("fetchrow", sql, args))
            if "FROM session_state" in sql:
                return {"state": current_state.model_dump_json()}
            raise AssertionError("idempotent retry must not insert feedback_memory")

        async def execute(self, sql, *args):
            raise AssertionError("idempotent retry must not rewrite state")

    async def fake_get_pool():
        return FakePool(FakeConn())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    result = await state_store.add_feedback(
        session_id="s1",
        job_id="job-1",
        outcome="offer",
        idempotency_key="feedback-request-1",
    )

    assert result.feedback_id == 9
    assert result.created is False
    assert result.feedback == {
        "feedback_id": 9,
        "job_id": "job-1",
        "outcome": "offer",
        "idempotency_key": "feedback-request-1",
    }
    assert [call[0] for call in calls if isinstance(call, tuple)] == ["fetchrow"]
    assert calls[-1] == "transaction_exit"


@pytest.mark.asyncio
async def test_state_store_feedback_rejects_conflicting_idempotency_payload(
    monkeypatch,
):
    from app.db import state_store
    from app.state.schema import SharedState

    current_state = SharedState(session_id="s1", user_id="u1")
    current_state.feedback_state.user_feedback = [
        {
            "feedback_id": 9,
            "job_id": "job-original",
            "outcome": "offer",
            "reason": "original reason",
            "user_rating": 5,
            "idempotency_key": "feedback-request-1",
            "closure_status": "processed",
            "case_written": True,
            "case_id": "case-9",
        }
    ]

    class FakeTransaction:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

        async def fetchrow(self, sql, *args):
            if "FROM session_state" in sql:
                return {"state": current_state.model_dump_json()}
            raise AssertionError("conflict must not insert feedback_memory")

        async def execute(self, sql, *args):
            raise AssertionError("conflict must not rewrite state")

    async def fake_get_pool():
        return FakePool(FakeConn())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    with pytest.raises(state_store.FeedbackIdempotencyConflict):
        await state_store.add_feedback(
            session_id="s1",
            job_id="job-conflict",
            outcome="rejected",
            reason="different reason",
            user_rating=1,
            idempotency_key="feedback-request-1",
        )


@pytest.mark.asyncio
async def test_mutate_state_atomically_locks_and_updates_state_without_status(
    monkeypatch,
):
    from app.db import state_store

    calls = []

    class FakeTransaction:
        async def __aenter__(self):
            calls.append("transaction_enter")

        async def __aexit__(self, exc_type, exc, tb):
            calls.append("transaction_exit")
            return False

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

        async def fetchrow(self, sql, *args):
            calls.append(("fetchrow", sql, args))
            return {
                "state": json.dumps(
                    {
                        "session_id": "s1",
                        "user_id": "u1",
                        "career_state": {"current_goal": ["existing goal"]},
                    }
                )
            }

        async def execute(self, sql, *args):
            calls.append(("execute", sql, args))

    async def fake_get_pool():
        return FakePool(FakeConn())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    def add_goal(state):
        state.career_state.current_goal.append("atomic goal")

    await state_store.mutate_state_atomically(session_id="s1", mutator=add_goal)

    assert calls[0] == "transaction_enter"
    select_sql = calls[1][1]
    update_sql, update_args = calls[2][1:]
    assert "FOR UPDATE" in select_sql
    assert "UPDATE session_state" in update_sql
    assert "status" not in update_sql.lower()
    assert json.loads(update_args[0])["career_state"]["current_goal"] == [
        "existing goal",
        "atomic goal",
    ]
    assert calls[3] == "transaction_exit"


@pytest.mark.asyncio
async def test_stale_stage_save_preserves_concurrently_committed_feedback_state(
    monkeypatch,
):
    from app.db import state_store
    from app.state.schema import SharedState

    calls = []
    persisted = SharedState(session_id="s1", user_id="u1")
    persisted.feedback_state.user_feedback = [
        {
            "feedback_id": 9,
            "job_id": "job-1",
            "outcome": "offer",
            "closure_status": "processed",
            "case_written": True,
            "case_id": "feedback-case-1",
        }
    ]
    persisted.feedback_state.case_soft_preferences = {
        "case_target_roles": ["Data Analyst"]
    }
    persisted.supervisor_log = [
        {
            "stage": "feedback_closure",
            "feedback_id": 9,
            "case_written": True,
        }
    ]

    stale_orchestrator_state = SharedState(session_id="s1", user_id="u1")
    stale_orchestrator_state.career_state.current_goal = ["new stage goal"]
    stale_orchestrator_state.supervisor_log = [
        {"stage": "planning", "retrieval_plan": {"top_k": 5}}
    ]

    class FakeTransaction:
        async def __aenter__(self):
            calls.append("transaction_enter")

        async def __aexit__(self, exc_type, exc, tb):
            calls.append("transaction_exit")
            return False

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

        async def fetchrow(self, sql, *args):
            calls.append(("fetchrow", sql, args))
            return {"state": persisted.model_dump_json()}

        async def execute(self, sql, *args):
            calls.append(("execute", sql, args))

    async def fake_get_pool():
        return FakePool(FakeConn())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    await state_store.save_state(stale_orchestrator_state, status="agentic_done")

    assert calls[0] == "transaction_enter"
    assert "ON CONFLICT (session_id) DO NOTHING" in calls[1][1]
    assert "FOR UPDATE" in calls[2][1]
    update_sql, update_args = calls[3][1:]
    written = json.loads(update_args[0])
    assert written["career_state"]["current_goal"] == ["new stage goal"]
    assert written["feedback_state"] == persisted.feedback_state.model_dump()
    assert written["supervisor_log"] == [
        {
            "stage": "feedback_closure",
            "feedback_id": 9,
            "case_written": True,
        },
        {"stage": "planning", "retrieval_plan": {"top_k": 5}},
    ]
    assert "status = $2" in update_sql
    assert update_args[1:] == ("agentic_done", "s1")
    assert calls[4] == "transaction_exit"


@pytest.mark.asyncio
async def test_save_state_establishes_session_row_before_acquiring_row_lock(
    monkeypatch,
):
    from app.db import state_store
    from app.state.schema import SharedState

    calls = []
    state = SharedState(session_id="new-session", user_id="u1")
    row_established = False

    class FakeTransaction:
        async def __aenter__(self):
            calls.append("transaction_enter")

        async def __aexit__(self, exc_type, exc, tb):
            calls.append("transaction_exit")
            return False

    class FakeConn:
        def transaction(self):
            return FakeTransaction()

        async def execute(self, sql, *args):
            nonlocal row_established
            calls.append(("execute", sql, args))
            if "INSERT INTO session_state" in sql:
                assert "ON CONFLICT (session_id) DO NOTHING" in sql
                row_established = True

        async def fetchrow(self, sql, *args):
            calls.append(("fetchrow", sql, args))
            assert row_established is True
            return {"state": state.model_dump_json()}

    async def fake_get_pool():
        return FakePool(FakeConn())

    monkeypatch.setattr(state_store, "get_pool", fake_get_pool)

    await state_store.save_state(state, status="resume_queued")

    assert calls[0] == "transaction_enter"
    assert calls[1][0] == "execute"
    assert calls[2][0] == "fetchrow"
    assert "FOR UPDATE" in calls[2][1]
    assert calls[3][0] == "execute"
    assert "status = $2" in calls[3][1]
    assert calls[4] == "transaction_exit"


def test_case_base_rejects_pii_and_builds_anonymous_embedding_text():
    from app.memory.case_base import CareerCase, build_case_embedding_text

    case = CareerCase(
        case_id="case-001",
        background_type="business_undergraduate_with_python",
        target_role="Data Analyst",
        successful_resume_features=["SQL project", "dashboard evidence"],
        missing_skills_before=["advanced SQL"],
        application_outcome="interview_1",
        recommended_bridge_roles=["Business Analyst Intern"],
    )

    text = build_case_embedding_text(case)

    assert "business_undergraduate_with_python" in text
    assert "Data Analyst" in text
    assert "john@" not in text.lower()

    with pytest.raises(ValueError):
        CareerCase(
            case_id="bad",
            background_type="john@example.com",
            target_role="Data Analyst",
            successful_resume_features=[],
            missing_skills_before=[],
            application_outcome="offer",
            recommended_bridge_roles=[],
        ).validate_anonymous()

    with pytest.raises(ValueError):
        CareerCase(
            case_id="raw-extra",
            background_type="business_undergraduate",
            target_role="Data Analyst",
            successful_resume_features=[],
            missing_skills_before=[],
            application_outcome="offer",
            recommended_bridge_roles=[],
            raw_resume_text="John Example john@example.com",
        )


@pytest.mark.asyncio
async def test_search_similar_cases_uses_query_embedding(monkeypatch):
    from app.memory import case_base

    class FakeConn:
        async def fetch(self, sql, *args):
            self.args = args
            return [
                {
                    "case_id": "case-001",
                    "background_type": "business_undergraduate",
                    "target_role": "Data Analyst",
                    "successful_resume_features": ["SQL project"],
                    "missing_skills_before": ["advanced SQL"],
                    "application_outcome": "interview_1",
                    "recommended_bridge_roles": ["Business Analyst Intern"],
                    "score": 0.9,
                }
            ]

    conn = FakeConn()

    async def fake_get_pool():
        return FakePool(conn)

    async def fake_embed_one(text):
        assert "analyst" in text
        return [0.1] * 1024

    monkeypatch.setattr(case_base, "get_pool", fake_get_pool)
    monkeypatch.setattr(case_base, "embed_one", fake_embed_one)

    rows = await case_base.search_similar_cases("analyst with SQL", top_k=3)

    assert rows[0]["case_id"] == "case-001"
    assert rows[0]["score"] == 0.9
    assert conn.args[1] == 3


def test_seed_cases_are_10_to_20_and_anonymous():
    from app.memory.case_base import contains_pii
    from scripts.seed_cases import DEFAULT_CASES

    assert 10 <= len(DEFAULT_CASES) <= 20
    for case in DEFAULT_CASES:
        case.validate_anonymous()
        assert contains_pii(case.background_type) is False
        assert "raw_resume" not in case.model_dump()


@pytest.mark.asyncio
async def test_seed_default_cases_upserts_10_to_20_anonymous_cases(monkeypatch):
    import scripts.seed_cases as seed_cases

    calls = []

    async def fake_upsert_career_case(case, *, embed_if_missing):
        case.validate_anonymous()
        calls.append((case.case_id, embed_if_missing, case.model_dump()))

    monkeypatch.setattr(seed_cases, "upsert_career_case", fake_upsert_career_case)

    count = await seed_cases.seed_default_cases(embed=False)

    assert 10 <= count <= 20
    assert len(calls) == count
    assert calls[0][0] == "case-001"
    assert all(embed_if_missing is False for _case_id, embed_if_missing, _ in calls)
    assert all("raw_resume" not in payload for _case_id, _embed, payload in calls)
