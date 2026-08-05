r"""答辩前彩排：三个 persona 各走一次完整真机流程。

Persona 覆盖：
  P1 陈晨   CN 后端（上海/北京，无需签证）        → 期望 CN 岗
  P2 李悦   UK 数据分析（伦敦，需要签证担保）      → 期望 UK 岗且全部可担保签证
  P3 王铭   金融转数据（爱丁堡/伦敦，转型桥接故事） → 期望 UK 岗，观察分层叙事

用法（先起服务器；console OTP 从日志读码）：
  $env:AUTH_ENFORCED = "true"; $env:EMAIL_OTP_PROVIDER = "console"
  .venv\Scripts\python -u -m app.serve *> tmp\rehearsal_server.log
  .venv\Scripts\python scripts\demo_rehearsal.py tmp\rehearsal_server.log
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
ORIGIN = {"Origin": "http://127.0.0.1:8000"}
LOG = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "tmp/rehearsal_server.log")
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
        f"{BASE}/sessions/{session_id}/resume-confirm", headers=ORIGIN
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


def main() -> None:
    reports = []
    failures = []
    for persona in PERSONAS:
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
    print()
    print(f"REHEARSAL TOTAL: {len(reports) - len(failures)}/{len(reports)} PASS")
    if failures:
        print("FAILED:", failures)
        sys.exit(1)


if __name__ == "__main__":
    main()
