r"""V2 全局多场景冒烟：真实服务器 + 真实 PG/pgvector + 真实 LLM/embedding。

用法（需先启动服务器并把 stdout 重定向到日志，console OTP 从日志读码）：
  $env:AUTH_ENFORCED = "true"
  .venv\Scripts\python -m app.serve *> tmp\smoke_server.log   # 后台
  .venv\Scripts\python scripts\global_smoke.py tmp\smoke_server.log

场景矩阵:
  A 认证:    邮箱 OTP 注册登录 / 错码拒绝 / 手机 OTP 第二用户 / 未登录 401
  B 主线:    建会话→传简历→确认→多轮咨询(真实 LLM)→CAS 409→确认单→执行→结果
             (真实向量检索, demo_synthetic 全程可见)→反馈(含非法 outcome 422)
  C 所有权:  B 用户访问 A 的会话/运行 404; 会话列表互不可见; 匿名 401
  D 错误路径: 不存在会话 404 / 错 plan_hash 409 / 未确认简历建 Brief 409
"""

import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
ORIGIN = {"Origin": "http://127.0.0.1:8000"}
LOG = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "tmp/smoke_server.log")
RESUME = ROOT / "data/resumes/demo_software_engineer_resume.docx"

RUN_ID = str(int(time.time()))[-7:]
EMAIL_A = f"smoke-{RUN_ID}@example.com"
PHONE_B = f"+86139{RUN_ID.zfill(8)}"

PASS = []
FAIL = []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"{'PASS' if ok else 'FAIL'} | {name}" + (f" | {detail}" if detail else ""))


def otp_codes(target: str) -> list[str]:
    text = LOG.read_text(encoding="utf-8", errors="replace")
    return re.findall(rf"\[development OTP\] \w+ {re.escape(target)}: (\d+)", text)


def login(client: httpx.Client, channel: str, target: str) -> dict:
    seen = len(otp_codes(target))
    r = client.post(f"{BASE}/auth/otp/request", json={"channel": channel, "target": target}, headers=ORIGIN)
    assert r.status_code == 202, f"otp request {r.status_code}: {r.text}"
    # 等新验证码真正落到服务器日志里，避免读到上一条旧码
    for _ in range(40):
        codes = otp_codes(target)
        if len(codes) > seen:
            break
        time.sleep(0.5)
    else:
        raise AssertionError(f"no fresh OTP for {target} in log")
    r = client.post(
        f"{BASE}/auth/otp/verify",
        json={"channel": channel, "target": target, "code": codes[-1]},
        headers=ORIGIN,
    )
    assert r.status_code == 200, f"otp verify {r.status_code}: {r.text}"
    # __Host- Cookie 带 Secure 标志，httpx cookiejar 拒绝在 http 上回传
    # （浏览器对 localhost 有豁免）；手动取 Set-Cookie 显式携带。
    set_cookie = r.headers.get("set-cookie", "")
    assert set_cookie.startswith("__Host-app_session="), set_cookie[:60]
    client.headers["Cookie"] = set_cookie.split(";", 1)[0]
    return r.json()


def main():
    a = httpx.Client(timeout=60)
    b = httpx.Client(timeout=60)
    anon = httpx.Client(timeout=30)

    # ---------- A 认证 ----------
    me_a = login(a, "email", EMAIL_A)
    check("A1 邮箱 OTP 注册登录", "user_id" in me_a, me_a.get("user_id", ""))
    r = a.get(f"{BASE}/me")
    check("A1b Cookie 会话生效 /me 200", r.status_code == 200, str(r.status_code))

    r = a.post(
        f"{BASE}/auth/otp/request",
        json={"channel": "email", "target": EMAIL_A},
        headers=ORIGIN,
    )
    time.sleep(1.0)
    r = a.post(
        f"{BASE}/auth/otp/verify",
        json={"channel": "email", "target": EMAIL_A, "code": "000000"},
        headers=ORIGIN,
    )
    check("A2 错误验证码被拒", r.status_code in (400, 401, 403, 422), str(r.status_code))

    me_b = login(b, "phone", PHONE_B)
    check("A3 手机 OTP 第二用户", me_b.get("user_id") not in (None, me_a.get("user_id")))

    r = anon.get(f"{BASE}/me")
    check("A4 未登录 /me 401", r.status_code == 401, str(r.status_code))

    # ---------- B 主线（用户 A）----------
    r = a.post(f"{BASE}/sessions", json={}, headers=ORIGIN)
    check("B1 创建会话", r.status_code in (200, 201), str(r.status_code))
    sid = r.json()["session_id"]

    with RESUME.open("rb") as fh:
        r = a.post(
            f"{BASE}/sessions/{sid}/resume",
            files={
                "file": (
                    RESUME.name,
                    fh,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            headers=ORIGIN,
        )
    check("B2 上传简历受理", r.status_code == 202, f"{r.status_code} {r.text[:120]}")

    preview = None
    for _ in range(60):
        r = a.get(f"{BASE}/sessions/{sid}/resume-preview")
        if r.status_code == 200:
            preview = r.json()
            break
        time.sleep(2)
    check(
        "B3 归一化完成且带证据",
        bool(preview) and bool(preview.get("evidence")),
        f"skills={len((preview or {}).get('skills', []))} evidence={len((preview or {}).get('evidence', []))}",
    )

    r = a.post(f"{BASE}/sessions/{sid}/resume-confirm", headers=ORIGIN)
    check("B4 确认简历档案", r.status_code == 200, str(r.status_code))

    turns = [
        "我想在上海或北京找后端开发或平台工程方向的工作，最好是科技公司",
        "我更看重成长空间和技术氛围，不考虑销售和纯运维岗位",
        "薪资希望不低于同级市场水平，可以接受少量出差",
    ]
    round_now = 0
    consult_ok = True
    for text in turns:
        r = a.post(
            f"{BASE}/sessions/{sid}/consult",
            json={"mode": "targeted", "message": text, "expected_round": round_now},
            headers=ORIGIN,
        )
        if r.status_code != 200:
            consult_ok = False
            print("consult turn failed:", r.status_code, r.text[:200])
            break
        data = r.json()
        round_now = data["round"]
    check("B5 多轮咨询(真实 LLM)", consult_ok and round_now == 3, f"round={round_now}")

    r = a.post(
        f"{BASE}/sessions/{sid}/consult",
        json={"mode": "targeted", "message": "再补充一点", "expected_round": 0},
        headers=ORIGIN,
    )
    check("B6 咨询 CAS 过期轮次 409", r.status_code == 409, str(r.status_code))

    r = a.get(f"{BASE}/sessions/{sid}/consult")
    state = r.json() if r.status_code == 200 else {}
    check(
        "B7 咨询状态可恢复",
        len(state.get("transcript", [])) == 3,
        f"transcript={len(state.get('transcript', []))} completeness={state.get('completeness')}",
    )

    # 自适应补槽：顾问没问够的必填项（目标/地点/签证）继续答，有界 ≤7 轮
    fillers = [
        "明确一下：我的求职目标就是后端工程师，地点上海或北京，我是中国公民，不需要签证担保",
        "偏好科技公司、成长空间大、技术氛围好的团队，没有其他要补充的了",
        "没有特别想避开的方向，销售除外",
        "以上信息都确认，无需再问",
    ]
    can_fin = bool(state.get("can_finalize"))
    last_completeness = state.get("completeness")
    filler_index = 0
    while not can_fin and round_now < 7 and filler_index < len(fillers):
        r = a.post(
            f"{BASE}/sessions/{sid}/consult",
            json={
                "mode": "targeted",
                "message": fillers[filler_index],
                "expected_round": round_now,
            },
            headers=ORIGIN,
        )
        filler_index += 1
        if r.status_code != 200:
            print("filler turn failed:", r.status_code, r.text[:200])
            break
        data = r.json()
        round_now = data["round"]
        can_fin = bool(data.get("can_finalize"))
        last_completeness = data.get("completeness")
    check(
        "B8a 有界多轮后达到可定稿",
        can_fin,
        f"round={round_now} completeness={last_completeness}",
    )

    r = a.post(f"{BASE}/sessions/{sid}/consult/finalize", headers=ORIGIN)
    check("B8 生成画像草稿", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
    draft = r.json() if r.status_code == 200 else {}
    if r.status_code != 200:
        print("ABORT: finalize failed")
        print(f"\nTOTAL: {len(PASS)} passed, {len(FAIL)} failed")
        sys.exit(1)

    r = a.post(
        f"{BASE}/sessions/{sid}/match-brief",
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
    check("B9 创建 Match Brief", r.status_code == 201, f"{r.status_code} {r.text[:150]}")
    brief = r.json()
    run_id = brief["run_id"]
    plan = brief["brief"]

    r = a.post(
        f"{BASE}/runs/{run_id}/execute",
        json={"plan_version": plan["plan_version"], "plan_hash": plan["plan_hash"]},
        headers=ORIGIN,
    )
    check("B10 提交执行受理", r.status_code in (200, 202), str(r.status_code))

    status = None
    for _ in range(150):
        r = a.get(f"{BASE}/runs/{run_id}/status")
        status = r.json()
        if status["status"] in {"completed", "completed_with_warnings", "failed", "cancelled"}:
            break
        time.sleep(3)
    check(
        "B11 运行完成",
        status is not None and status["status"] in {"completed", "completed_with_warnings"},
        f"status={status and status['status']} stage={status and status.get('stage')} err={status and status.get('error_code')}",
    )

    r = a.get(f"{BASE}/runs/{run_id}/conversation")
    conv = r.json() if r.status_code == 200 else {}
    personas = {m.get("persona") for m in conv.get("messages", [])}
    check("B12 群聊播报四角色", bool({"pm", "job_scout"} & personas), f"personas={sorted(personas)}")

    r = a.get(f"{BASE}/runs/{run_id}/result")
    result = (r.json() or {}).get("result") or {}
    roles = result.get("recommended_roles") or []
    demo_flags = [x.get("demo_synthetic") for x in roles]
    countries = {x.get("country_code") for x in roles}
    with_evidence = all(x.get("evidence") for x in roles)
    check("B13 结果含推荐岗位", len(roles) > 0, f"n={len(roles)} summary={result.get('summary','')[:60]}")
    check(
        "B14 演示语料标记全程可见",
        len(roles) > 0 and all(f is True for f in demo_flags) and countries <= {"CN", "UK"},
        f"demo={demo_flags} countries={sorted(str(c) for c in countries)}",
    )
    check("B15 每条推荐带 JD 证据", len(roles) > 0 and with_evidence)

    if roles:
        r = a.post(
            f"{BASE}/runs/{run_id}/reaction",
            json={"job_id": roles[0]["job_id"], "outcome": "interview", "user_rating": 5},
            headers=ORIGIN,
        )
        check("B16 提交反馈", r.status_code == 202, f"{r.status_code} {r.text[:100]}")
        r = a.post(
            f"{BASE}/runs/{run_id}/reaction",
            json={"job_id": roles[0]["job_id"], "outcome": "not-a-real-outcome"},
            headers=ORIGIN,
        )
        check("B16b 非法 outcome 422", r.status_code == 422, str(r.status_code))

    # ---------- C 所有权 ----------
    for name, resp in {
        "C1 B 读 A 会话咨询 404": b.get(f"{BASE}/sessions/{sid}/consult"),
        "C2 B 读 A 简历预览 404": b.get(f"{BASE}/sessions/{sid}/resume-preview"),
        "C3 B 读 A 运行状态 404": b.get(f"{BASE}/runs/{run_id}/status"),
    }.items():
        check(name, resp.status_code == 404, str(resp.status_code))

    r = a.get(f"{BASE}/me/sessions")
    a_sessions = {s["session_id"] for s in r.json().get("sessions", [])}
    r = b.get(f"{BASE}/me/sessions")
    b_sessions = {s["session_id"] for s in r.json().get("sessions", [])}
    check("C4 会话列表隔离", sid in a_sessions and sid not in b_sessions)

    r = anon.get(f"{BASE}/sessions/{sid}/consult")
    check("C5 匿名读 A 会话被拒", r.status_code in (401, 404), str(r.status_code))

    # ---------- D 错误路径 ----------
    r = a.get(f"{BASE}/sessions/does-not-exist/consult")
    check("D1 不存在会话 404", r.status_code == 404, str(r.status_code))

    r = a.post(
        f"{BASE}/runs/{run_id}/execute",
        json={"plan_version": plan["plan_version"], "plan_hash": "f" * 64},
        headers=ORIGIN,
    )
    check("D2 错误 plan_hash 409", r.status_code == 409, str(r.status_code))

    # 咨询本身不要求简历（设计如此：小意可先聊）；简历门槛在 match-brief
    r = a.post(f"{BASE}/sessions", json={}, headers=ORIGIN)
    sid2 = r.json()["session_id"]
    r = a.post(
        f"{BASE}/sessions/{sid2}/match-brief",
        json={
            "career_goal": "backend engineer roles",
            "hard_constraints": {},
            "soft_preferences": {},
            "avoid_roles": [],
            "result_count": 5,
            "needs_clarification": False,
        },
        headers=ORIGIN,
    )
    check(
        "D3 未确认简历直接建 Brief 被拒",
        r.status_code in (400, 404, 409, 412, 422),
        f"{r.status_code} {r.text[:100]}",
    )

    print()
    print(f"TOTAL: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
