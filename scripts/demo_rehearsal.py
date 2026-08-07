r"""答辩前彩排：四个 persona 各走一次完整真机流程。

Persona 覆盖：
  P1 陈晨   CN 后端（上海/北京，无需签证）        → 期望 CN 岗
  P2 李悦   UK 数据分析（伦敦，需要签证担保）      → 期望 UK 岗且全部可担保签证
  P3 王铭   金融转数据（爱丁堡/伦敦，转型桥接故事） → 期望 UK 岗，观察分层叙事
  P4 林安   简历含糊（伦敦数据分析，需要签证担保）  → 澄清证据 + PM 三触发

用法（先起服务器；console OTP 从日志读码）：
  $env:AUTH_ENFORCED = "true"; $env:EMAIL_OTP_PROVIDER = "console"
  .venv\Scripts\python -u -m app.serve *> tmp\rehearsal_server.log
  .venv\Scripts\python scripts\demo_rehearsal.py tmp\rehearsal_server.log
  .venv\Scripts\python scripts\demo_rehearsal.py tmp\rehearsal_server.log --personas p4
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
ORIGIN = {"Origin": "http://127.0.0.1:8000"}
LOG = ROOT / "tmp/rehearsal_server.log"
RUN_ID = str(int(time.time()))[-7:]

PERSONAS = [
    {
        "name": "P1 陈晨 · CN 后端",
        "email": f"chen-{RUN_ID}@example.com",
        "resume": ROOT / "data/resumes/rehearsal/cn_backend_chen.txt",
        "turns": [
            "我想在上海或北京找后端工程师的工作，目标就是后端开发方向",
            "我是中国公民，不需要签证担保；偏好科技公司、技术氛围好的团队",
            "不考虑销售岗位，其他没有要补充的了",
        ],
        "expect_countries": {"CN"},
    },
    {
        "name": "P2 李悦 · UK 数据分析（需签证）",
        "email": f"li-{RUN_ID}@example.com",
        "resume": ROOT / "data/resumes/rehearsal/uk_data_li.txt",
        "turns": [
            "我想在 London 找 data analyst 数据分析方向的工作，目标是数据分析师",
            "我目前是学生签证，需要雇主提供 Skilled Worker 签证担保，这是硬性要求",
            "偏好有导师制度的团队，不考虑纯销售岗位，其他没有了",
        ],
        "expect_countries": {"UK"},
    },
    {
        "name": "P3 王铭 · 金融转数据（桥接）",
        "email": f"wang-{RUN_ID}@example.com",
        "resume": ROOT / "data/resumes/rehearsal/bridge_finance_wang.txt",
        "turns": [
            "我在 Edinburgh，也接受 London，想从金融分析转向数据方向，目标是数据分析或数据工程",
            "我有永居身份，不需要签证担保；能接受先做金融与数据结合的过渡岗位",
            "不想做纯客服类岗位，其他没有要补充的了",
        ],
        "expect_countries": {"UK"},
    },
]

FILLERS = [
    "补充确认：目标、地点和签证情况就是我刚才说的，没有变化",
    "没有其他偏好了，可以生成确认单",
    "以上都确认，无需再问",
]

P4_NAME = "P4 林安 · 简历含糊者"
P4_RESUME_TEXT = """Lin An
Email: lin.an@example.com
Location: London, UK

EDUCATION
University of Birmingham — MSc Business Analytics, 2024-2025

EXPERIENCE
BrightMart Retail — Data Intern, March 2025-June 2025
Responsibilities: N/A
Achievements: N/A

Campus Analytics Society — Volunteer Analyst, September 2024-February 2025
Responsibilities: N/A
Achievements: N/A

PERSONAL FACT BANK FOR FOLLOW-UP
I used Python, pandas and SQL to clean 12,480 sales records and reduced the
weekly dashboard refresh time by 31 percent.

SKILLS
Python, pandas, SQL, Excel, Power BI
"""
P4_CLARIFICATION_ANSWER = (
    "我曾使用 Python、pandas 和 SQL 清洗 12,480 条销售记录，"
    "并把每周仪表盘刷新时间缩短了 31%。"
)
P4_CONSULT_MESSAGES = (
    "你好，小意，今天辛苦了。",
    "谢谢，先继续吧。",
    (
        "我的当前目标是 Data Analyst，工作地点只考虑 London；"
        "我持 Student visa，入职需要雇主提供 Skilled Worker visa sponsorship。"
    ),
    "目标、地点和签证三项硬条件已经确认，请基于已上传的简历继续下一步。",
    P4_CLARIFICATION_ANSWER,
    "跳过",
    "暂时没有其他偏好需要补充，请继续。",
)


def otp_codes(target: str) -> list[str]:
    text = LOG.read_text(encoding="utf-8", errors="replace")
    return re.findall(
        rf"\[development OTP\] \w+ {re.escape(target)}: (\d+)", text
    )


def login(client: httpx.Client, email: str) -> None:
    seen = len(otp_codes(email))
    response = client.post(
        f"{BASE}/auth/otp/request",
        json={"channel": "email", "target": email},
        headers=ORIGIN,
    )
    assert response.status_code == 202, response.text
    for _ in range(40):
        codes = otp_codes(email)
        if len(codes) > seen:
            break
        time.sleep(0.5)
    else:
        raise AssertionError(f"no OTP for {email}")
    response = client.post(
        f"{BASE}/auth/otp/verify",
        json={"channel": "email", "target": email, "code": codes[-1]},
        headers=ORIGIN,
    )
    assert response.status_code == 200, response.text
    set_cookie = response.headers.get("set-cookie", "")
    client.headers["Cookie"] = set_cookie.split(";", 1)[0]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "server_log",
        nargs="?",
        default="tmp/rehearsal_server.log",
        help="包含 console OTP 的服务日志路径（相对仓库根目录或绝对路径）",
    )
    parser.add_argument(
        "--personas",
        nargs="+",
        choices=("p1", "p2", "p3", "p4"),
        default=("p1", "p2", "p3", "p4"),
        help="只运行指定 persona；默认运行 p1 p2 p3 p4",
    )
    return parser.parse_args(argv)


def p4_switch_status() -> tuple[bool, str]:
    # 脚本可从任意 CWD 直跑：导入 app.* 前确保仓库根在 sys.path
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.config import settings

    detail = (
        f"RESUME_CLARIFY_ENABLED={settings.resume_clarify_enabled}, "
        f"CONSULT_COACH_ENABLED={settings.consult_coach_enabled}"
    )
    return (
        settings.resume_clarify_enabled and settings.consult_coach_enabled,
        detail,
    )


def _p4_check(label: str, condition: bool, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(
        f"  [{'PASS' if condition else 'FAIL'}] {label}{suffix}",
        flush=True,
    )
    if not condition:
        raise AssertionError(f"{label}: {detail or 'assertion failed'}")


async def _load_p4_db_snapshot_async(session_id: str) -> dict[str, Any]:
    import asyncpg

    from app.config import settings

    connection = await asyncpg.connect(dsn=settings.database_url)
    try:
        row = await connection.fetchrow(
            """
            SELECT state, status, resume_version, confirmed_resume_version
            FROM session_state
            WHERE session_id = $1
            """,
            session_id,
        )
    finally:
        await connection.close()
    if row is None:
        raise AssertionError(f"session_state row missing for {session_id}")
    raw_state = row["state"]
    if isinstance(raw_state, (str, bytes, bytearray)):
        state = json.loads(raw_state)
    elif isinstance(raw_state, dict):
        state = raw_state
    else:
        raise AssertionError(
            f"unexpected session_state.state type: {type(raw_state).__name__}"
        )
    return {
        "state": state,
        "status": row["status"],
        "resume_version": int(row["resume_version"] or 0),
        "confirmed_resume_version": (
            int(row["confirmed_resume_version"])
            if row["confirmed_resume_version"] is not None
            else None
        ),
    }


def _load_p4_db_snapshot(session_id: str) -> dict[str, Any]:
    return asyncio.run(_load_p4_db_snapshot_async(session_id))


def _required_slot_count(profile: dict[str, Any]) -> int:
    hard = profile.get("hard_constraints") or {}
    has_goal = bool(profile.get("current_goal"))
    has_location = bool(hard.get("locations")) or hard.get("remote") is True
    has_visa = isinstance(hard.get("need_visa_sponsor"), bool)
    return sum((has_goal, has_location, has_visa))


def _post_p4_turn(
    client: httpx.Client,
    session_id: str,
    *,
    expected_round: int,
    message: str,
) -> dict[str, Any]:
    round_number = expected_round + 1
    response = client.post(
        f"{BASE}/sessions/{session_id}/consult",
        json={
            "mode": "targeted",
            "message": message,
            "expected_round": expected_round,
        },
        headers=ORIGIN,
    )
    _p4_check(
        f"r{round_number} consult HTTP 200",
        response.status_code == 200,
        f"status={response.status_code} body={response.text[:300]}",
    )
    payload = response.json()
    _p4_check(
        f"r{round_number} round CAS",
        payload.get("round") == round_number,
        f"observed_round={payload.get('round')}",
    )
    return payload


def _p4_note_for_round(
    client: httpx.Client,
    session_id: str,
    *,
    round_number: int,
    trigger: str,
) -> dict[str, Any]:
    response = client.get(f"{BASE}/sessions/{session_id}/consult")
    _p4_check(
        f"r{round_number} GET /consult",
        response.status_code == 200,
        f"status={response.status_code} body={response.text[:300]}",
    )
    transcript = response.json().get("transcript") or []
    turn = next(
        (item for item in transcript if item.get("round") == round_number),
        None,
    )
    notes = turn.get("supervisor_notes") if isinstance(turn, dict) else []
    matches = [
        note
        for note in (notes or [])
        if isinstance(note, dict) and note.get("trigger") == trigger
    ]
    valid = (
        len(matches) == 1
        and matches[0].get("kind") == "coach"
        and matches[0].get("verdict") in {"pass", "advise"}
        and bool(str(matches[0].get("text") or "").strip())
    )
    _p4_check(
        f"r{round_number} PM trigger={trigger}",
        valid,
        f"notes={json.dumps(notes or [], ensure_ascii=False)}",
    )
    return matches[0]


def _c_ids(values: Any) -> set[str]:
    return {
        str(value)
        for value in (values or [])
        if re.fullmatch(r"C\d{3}", str(value))
    }


def _result_citations(result: dict[str, Any]) -> set[str]:
    citations: set[str] = set()
    for role in result.get("recommended_roles") or []:
        if not isinstance(role, dict):
            continue
        citations.update(
            str(item.get("evidence_span_id"))
            for item in role.get("resume_evidence") or []
            if isinstance(item, dict)
            and re.fullmatch(r"C\d{3}", str(item.get("evidence_span_id")))
        )
    for field_name in ("resume_strategy", "skill_gaps", "career_path"):
        for item in result.get(field_name) or []:
            if isinstance(item, dict):
                citations.update(_c_ids(item.get("evidence_span_ids")))
    return citations


def _strategy_citations(state: dict[str, Any]) -> set[str]:
    strategy = state.get("strategy_state") or {}
    citations: set[str] = set()
    for field_name in (
        "recommended_roles",
        "resume_revision_plan",
        "skill_gap_analysis",
        "career_path",
    ):
        for item in strategy.get(field_name) or []:
            if not isinstance(item, dict):
                continue
            citations.update(_c_ids(item.get("resume_evidence_span_ids")))
            citations.update(_c_ids(item.get("evidence_span_ids")))
    return citations


def run_persona(persona: dict) -> dict:
    client = httpx.Client(timeout=90)
    login(client, persona["email"])

    session_id = client.post(
        f"{BASE}/sessions", json={}, headers=ORIGIN
    ).json()["session_id"]

    with persona["resume"].open("rb") as handle:
        response = client.post(
            f"{BASE}/sessions/{session_id}/resume",
            files={"file": (persona["resume"].name, handle, "text/plain")},
            headers=ORIGIN,
        )
    assert response.status_code == 202, response.text

    for _ in range(60):
        response = client.get(f"{BASE}/sessions/{session_id}/resume-preview")
        if response.status_code == 200:
            break
        time.sleep(2)
    assert response.status_code == 200, "resume normalization timed out"
    assert client.post(
        f"{BASE}/sessions/{session_id}/resume-confirm",
        json={"expected_resume_version": response.json()["resume_version"]},
        headers=ORIGIN,
    ).status_code == 200

    round_now = 0
    can_finalize = False
    for message in list(persona["turns"]) + FILLERS:
        response = client.post(
            f"{BASE}/sessions/{session_id}/consult",
            json={
                "mode": "targeted",
                "message": message,
                "expected_round": round_now,
            },
            headers=ORIGIN,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        round_now = payload["round"]
        can_finalize = payload["can_finalize"]
        if can_finalize and message in FILLERS:
            break
    assert can_finalize, "consultation never reached can_finalize"

    draft = client.post(
        f"{BASE}/sessions/{session_id}/consult/finalize", headers=ORIGIN
    ).json()
    brief = client.post(
        f"{BASE}/sessions/{session_id}/match-brief",
        json={
            "career_goal": draft["career_goal"],
            "hard_constraints": draft.get("hard_constraints") or {},
            "soft_preferences": draft.get("soft_preferences") or {},
            "avoid_roles": draft.get("avoid_roles") or [],
            "result_count": draft.get("result_count") or 5,
            "needs_clarification": False,
        },
        headers=ORIGIN,
    ).json()
    run_id = brief["run_id"]
    plan = brief["brief"]
    response = client.post(
        f"{BASE}/runs/{run_id}/execute",
        json={
            "plan_version": plan["plan_version"],
            "plan_hash": plan["plan_hash"],
        },
        headers=ORIGIN,
    )
    assert response.status_code in (200, 202), response.text

    status = {}
    for _ in range(150):
        status = client.get(f"{BASE}/runs/{run_id}/status").json()
        if status["status"] in {
            "completed",
            "completed_with_warnings",
            "failed",
            "cancelled",
        }:
            break
        time.sleep(3)

    result = (
        client.get(f"{BASE}/runs/{run_id}/result").json().get("result") or {}
    )
    roles = result.get("recommended_roles") or []
    return {
        "persona": persona["name"],
        "brief_constraints": plan.get("hard_constraints"),
        "run_status": status.get("status"),
        "warnings": result.get("warnings") or [],
        "roles": [
            {
                "title": role.get("title"),
                "company": role.get("company"),
                "location": role.get("location"),
                "tier": role.get("tier"),
                "country": role.get("country_code"),
                "demo": role.get("demo_synthetic"),
            }
            for role in roles
        ],
        "countries": sorted(
            {str(role.get("country_code")) for role in roles}
        ),
        "expected_countries": sorted(persona["expect_countries"]),
    }


def run_p4() -> dict[str, Any]:
    email = f"lin-{RUN_ID}@example.com"
    with httpx.Client(timeout=90) as client:
        login(client, email)
        _p4_check("setup OTP login", bool(client.headers.get("Cookie")))

        response = client.post(f"{BASE}/sessions", json={}, headers=ORIGIN)
        _p4_check(
            "setup create session",
            response.status_code in {200, 201},
            f"status={response.status_code} body={response.text[:300]}",
        )
        session_id = response.json()["session_id"]

        response = client.post(
            f"{BASE}/sessions/{session_id}/resume",
            files={
                "file": (
                    "p4_ambiguous_resume.txt",
                    P4_RESUME_TEXT.encode("utf-8"),
                    "text/plain",
                )
            },
            headers=ORIGIN,
        )
        _p4_check(
            "setup upload embedded ambiguous resume",
            response.status_code == 202,
            f"status={response.status_code} body={response.text[:300]}",
        )

        preview: dict[str, Any] = {}
        for _ in range(60):
            response = client.get(
                f"{BASE}/sessions/{session_id}/resume-preview"
            )
            if response.status_code == 200:
                preview = response.json()
                break
            time.sleep(2)
        _p4_check(
            "setup resume normalization",
            response.status_code == 200,
            f"last_status={response.status_code} body={response.text[:300]}",
        )
        response = client.post(
            f"{BASE}/sessions/{session_id}/resume-confirm",
            json={"expected_resume_version": preview.get("resume_version")},
            headers=ORIGIN,
        )
        _p4_check(
            "setup confirm normalized resume",
            response.status_code == 200,
            f"status={response.status_code} body={response.text[:300]}",
        )

        snapshot = _load_p4_db_snapshot(session_id)
        resume_state = snapshot["state"].get("resume_state") or {}
        targets = [
            item
            for item in resume_state.get("clarification_targets") or []
            if isinstance(item, dict)
        ]
        target_paths = [str(item.get("field_path") or "") for item in targets]
        deterministic_target_ready = (
            len(targets) == 2
            and all(item.get("status") == "open" for item in targets)
            and any(path.startswith("experience[") for path in target_paths)
        )
        _p4_check(
            "setup deterministic ambiguity targets=2",
            deterministic_target_ready,
            f"target_paths={target_paths}",
        )

        r1 = _post_p4_turn(
            client,
            session_id,
            expected_round=0,
            message=P4_CONSULT_MESSAGES[0],
        )
        _p4_check(
            "r1 zero progress while slots incomplete",
            not r1.get("can_finalize")
            and _required_slot_count(r1.get("profile_draft") or {}) == 0,
            f"profile={json.dumps(r1.get('profile_draft'), ensure_ascii=False)}",
        )

        r2 = _post_p4_turn(
            client,
            session_id,
            expected_round=1,
            message=P4_CONSULT_MESSAGES[1],
        )
        _p4_check(
            "r2 second zero-progress turn",
            not r2.get("can_finalize")
            and _required_slot_count(r2.get("profile_draft") or {}) == 0,
            f"profile={json.dumps(r2.get('profile_draft'), ensure_ascii=False)}",
        )
        stagnation_note = _p4_note_for_round(
            client,
            session_id,
            round_number=2,
            trigger="stagnation",
        )

        r3 = _post_p4_turn(
            client,
            session_id,
            expected_round=2,
            message=P4_CONSULT_MESSAGES[2],
        )
        r3_profile = r3.get("profile_draft") or {}
        r3_hard = r3_profile.get("hard_constraints") or {}
        r3_locations = [
            str(value).casefold() for value in r3_hard.get("locations") or []
        ]
        _p4_check(
            "r3 fills target/location/visa slots",
            r3.get("can_finalize") is True
            and _required_slot_count(r3_profile) == 3
            and r3_hard.get("need_visa_sponsor") is True
            and "london" in r3_locations,
            f"profile={json.dumps(r3_profile, ensure_ascii=False)}",
        )

        r4 = _post_p4_turn(
            client,
            session_id,
            expected_round=3,
            message=P4_CONSULT_MESSAGES[3],
        )
        r4_progress = r4.get("clarification_progress") or {}
        _p4_check(
            "r4 enters resume_clarify and asks target 1",
            r4.get("phase") == "resume_clarify"
            and r4.get("can_finalize") is True
            and r4_progress.get("total") == 2
            and r4_progress.get("questions_used") == 1,
            (
                f"phase={r4.get('phase')} "
                f"progress={json.dumps(r4_progress, ensure_ascii=False)}"
            ),
        )
        snapshot = _load_p4_db_snapshot(session_id)
        pending = (
            snapshot["state"].get("resume_state") or {}
        ).get("pending_clarification_question")
        _p4_check(
            "r4 pending clarification anchor persisted",
            isinstance(pending, dict) and pending.get("asked_round") == 4,
            f"pending={json.dumps(pending, ensure_ascii=False)}",
        )

        r5 = _post_p4_turn(
            client,
            session_id,
            expected_round=4,
            message=P4_CONSULT_MESSAGES[4],
        )
        r5_progress = r5.get("clarification_progress") or {}
        _p4_check(
            "r5 substantive clarification answered=1",
            r5_progress.get("answered") == 1
            and r5_progress.get("skipped") == 0,
            f"progress={json.dumps(r5_progress, ensure_ascii=False)}",
        )
        snapshot = _load_p4_db_snapshot(session_id)
        resume_state = snapshot["state"].get("resume_state") or {}
        clarification_spans = [
            item
            for item in resume_state.get("clarification_evidence_spans") or []
            if isinstance(item, dict)
        ]
        exact_spans = [
            item
            for item in clarification_spans
            if re.fullmatch(r"C\d{3}", str(item.get("span_id") or ""))
            and item.get("source") == "user_clarification"
            and item.get("text") == P4_CLARIFICATION_ANSWER
        ]
        _p4_check(
            "r5 C### span.text equals user answer verbatim",
            len(exact_spans) == 1,
            (
                "spans="
                + json.dumps(clarification_spans, ensure_ascii=False)[:600]
            ),
        )
        clarification_span_id = str(exact_spans[0]["span_id"])

        r6 = _post_p4_turn(
            client,
            session_id,
            expected_round=5,
            message=P4_CONSULT_MESSAGES[5],
        )
        r6_progress = r6.get("clarification_progress") or {}
        _p4_check(
            "r6 skip exhausts targets and keeps can_finalize",
            r6.get("can_finalize") is True
            and r6_progress.get("answered") == 1
            and r6_progress.get("skipped") == 1
            and r6_progress.get("total") == 2
            and r6_progress.get("questions_used") == 2,
            f"progress={json.dumps(r6_progress, ensure_ascii=False)}",
        )
        finalizable_note = _p4_note_for_round(
            client,
            session_id,
            round_number=6,
            trigger="finalizable",
        )

        r7 = _post_p4_turn(
            client,
            session_id,
            expected_round=6,
            message=P4_CONSULT_MESSAGES[6],
        )
        _p4_check(
            "r7 enters deepen within eight-round budget",
            r7.get("phase") == "deepen" and r7.get("round") == 7,
            f"phase={r7.get('phase')} round={r7.get('round')}",
        )
        deepen_note = _p4_note_for_round(
            client,
            session_id,
            round_number=7,
            trigger="deepen_entry",
        )

        response = client.post(
            f"{BASE}/sessions/{session_id}/consult/finalize",
            headers=ORIGIN,
        )
        _p4_check(
            "r8 finalize consultation",
            response.status_code == 200,
            f"status={response.status_code} body={response.text[:300]}",
        )
        draft = response.json()
        response = client.post(
            f"{BASE}/sessions/{session_id}/match-brief",
            json={
                "career_goal": draft["career_goal"],
                "hard_constraints": draft.get("hard_constraints") or {},
                "soft_preferences": draft.get("soft_preferences") or {},
                "avoid_roles": draft.get("avoid_roles") or [],
                "result_count": draft.get("result_count") or 5,
                "needs_clarification": False,
            },
            headers=ORIGIN,
        )
        _p4_check(
            "r8 create match brief",
            response.status_code == 201,
            f"status={response.status_code} body={response.text[:300]}",
        )
        brief_payload = response.json()
        run_id = brief_payload["run_id"]
        plan = brief_payload["brief"]
        response = client.post(
            f"{BASE}/runs/{run_id}/execute",
            json={
                "plan_version": plan["plan_version"],
                "plan_hash": plan["plan_hash"],
            },
            headers=ORIGIN,
        )
        _p4_check(
            "r8 execute accepted",
            response.status_code in {200, 202},
            f"status={response.status_code} body={response.text[:300]}",
        )

        status: dict[str, Any] = {}
        for _ in range(150):
            response = client.get(f"{BASE}/runs/{run_id}/status")
            if response.status_code != 200:
                _p4_check(
                    "r8 poll status HTTP 200",
                    False,
                    (
                        f"status={response.status_code} "
                        f"body={response.text[:300]}"
                    ),
                )
            status = response.json()
            if status.get("status") in {
                "completed",
                "completed_with_warnings",
                "failed",
                "cancelled",
            }:
                break
            time.sleep(3)
        _p4_check(
            "r8 run completed",
            status.get("status") == "completed",
            f"run_status={status.get('status')}",
        )

        response = client.get(f"{BASE}/runs/{run_id}/result")
        _p4_check(
            "result HTTP 200",
            response.status_code == 200,
            f"status={response.status_code} body={response.text[:300]}",
        )
        result = response.json().get("result") or {}
        roles = result.get("recommended_roles") or []
        countries = {
            str(role.get("country_code"))
            for role in roles
            if isinstance(role, dict)
        }
        _p4_check(
            "result contains UK demo matches",
            bool(roles)
            and countries <= {"UK"}
            and all(role.get("demo_synthetic") is True for role in roles),
            f"role_count={len(roles)} countries={sorted(countries)}",
        )

        snapshot = _load_p4_db_snapshot(session_id)
        state = snapshot["state"]
        public_citations = _result_citations(result)
        strategy_citations = _strategy_citations(state)
        citation_surface = (
            "run result"
            if clarification_span_id in public_citations
            else "state.strategy_state"
        )
        _p4_check(
            "result/strategy evidence chain cites C###",
            clarification_span_id in public_citations | strategy_citations,
            (
                f"expected={clarification_span_id} "
                f"public={sorted(public_citations)} "
                f"strategy={sorted(strategy_citations)}"
            ),
        )

        reservations = [
            item
            for item in state.get("coach_reservations") or []
            if isinstance(item, dict)
        ]
        reservation_triplets = [
            (item.get("trigger"), item.get("status"), item.get("round"))
            for item in reservations
        ]
        expected_triplets = [
            ("stagnation", "succeeded", 2),
            ("finalizable", "succeeded", 6),
            ("deepen_entry", "succeeded", 7),
        ]
        _p4_check(
            "coach budget exhausted exactly 3/3 in required order",
            reservation_triplets == expected_triplets,
            f"reservations={reservation_triplets}",
        )
        terminal_logs = {
            str(item.get("coach_attempt_id")): item
            for item in state.get("supervisor_log") or []
            if isinstance(item, dict) and item.get("stage") == "consult_coach"
        }
        verdicts_dual_logged = all(
            (
                terminal_logs.get(str(reservation.get("coach_attempt_id")))
                or {}
            ).get("verdict")
            in {"pass", "advise"}
            and (
                terminal_logs.get(str(reservation.get("coach_attempt_id")))
                or {}
            ).get("status")
            == "succeeded"
            for reservation in reservations
        )
        _p4_check(
            "coach verdicts persisted in supervisor_log",
            len(terminal_logs) == 3 and verdicts_dual_logged,
            f"terminal_log_count={len(terminal_logs)}",
        )
        _p4_check(
            "resume confirmation remains current after matching",
            snapshot["resume_version"] > 0
            and snapshot["confirmed_resume_version"]
            == snapshot["resume_version"],
            (
                f"resume_version={snapshot['resume_version']} "
                f"confirmed={snapshot['confirmed_resume_version']}"
            ),
        )

    return {
        "persona": P4_NAME,
        "session_id": session_id,
        "run_id": run_id,
        "run_status": status.get("status"),
        "role_count": len(roles),
        "clarification_span_id": clarification_span_id,
        "citation_surface": citation_surface,
        "coach_triggers": [item[0] for item in reservation_triplets],
        "coach_notes": [
            stagnation_note["verdict"],
            finalizable_note["verdict"],
            deepen_note["verdict"],
        ],
    }


def main() -> None:
    args = parse_args()
    log_path = Path(args.server_log)
    global LOG
    LOG = log_path if log_path.is_absolute() else ROOT / log_path
    selected = set(args.personas)
    reports = []
    failures = []
    skipped = []
    for index, persona in enumerate(PERSONAS, start=1):
        if f"p{index}" not in selected:
            continue
        print(f"===== {persona['name']} =====", flush=True)
        report = run_persona(persona)
        reports.append(report)
        ok_status = report["run_status"] in {
            "completed",
            "completed_with_warnings",
        }
        ok_roles = bool(report["roles"])
        ok_country = set(report["countries"]) <= set(
            report["expected_countries"]
        )
        ok_demo = all(role["demo"] is True for role in report["roles"])
        for line in report["roles"]:
            print("  ", json.dumps(line, ensure_ascii=False), flush=True)
        verdict = ok_status and ok_roles and ok_country and ok_demo
        print(
            f"  status={report['run_status']} countries={report['countries']} "
            f"expected={report['expected_countries']} demo_all={ok_demo} "
            f"warnings={report['warnings']} -> {'PASS' if verdict else 'FAIL'}",
            flush=True,
        )
        if not verdict:
            failures.append(report["persona"])

    if "p4" in selected:
        print(f"===== {P4_NAME} =====", flush=True)
        enabled, switch_detail = p4_switch_status()
        if not enabled:
            skipped.append(P4_NAME)
            print(
                "  [SKIP] P4 requires both feature switches enabled — "
                f"{switch_detail}",
                flush=True,
            )
        else:
            try:
                report = run_p4()
            except AssertionError as exc:
                reports.append({"persona": P4_NAME})
                failures.append(P4_NAME)
                print(f"  P4 SUMMARY -> FAIL: {exc}", flush=True)
            else:
                reports.append(report)
                print(
                    "  P4 SUMMARY "
                    f"session_id={report['session_id']} run_id={report['run_id']} "
                    f"status={report['run_status']} roles={report['role_count']} "
                    f"evidence={report['clarification_span_id']}@"
                    f"{report['citation_surface']} "
                    f"coach={report['coach_triggers']} -> PASS",
                    flush=True,
                )
    print()
    summary = (
        f"REHEARSAL TOTAL: {len(reports) - len(failures)}/"
        f"{len(reports)} PASS"
    )
    if skipped:
        summary = f"{summary}; {len(skipped)} SKIP"
    print(summary)
    if skipped:
        print("SKIPPED:", skipped)
    if failures:
        print("FAILED:", failures)
        sys.exit(1)


if __name__ == "__main__":
    main()
