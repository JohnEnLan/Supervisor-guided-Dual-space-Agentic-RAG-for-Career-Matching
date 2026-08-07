# 批次 9 总验收报告（版本化，2026-08-07）

**验收 SHA**：`4cd5b28770dcb4994c9296da2361a61df12dd3f0`（全局逐段审核三方
PASS 后的最终提交；本报告与 rehearsal 脚本修正在其后一提交入库）。

## 一、门禁（最终 SHA 全量复跑，Claude 本机）

| 门 | 结果 |
|---|---|
| 后端 pytest（含四组合等价矩阵、竞态五件套、隐私升格回归） | **642 passed** |
| pyflakes app scripts | 0 |
| 前端 typecheck / build | 0 / 成功 |
| Vitest（含跨会话泄漏与 error→重传→ready 回归） | **105/105** |
| Playwright（桌面 13 + 移动 1，含 finalizable CTA 与移动真发送场景） | **14/14** |
| 契约链 export → api:generate → api:check | 0，diff 全程审计为加性 |

## 二、32 项全局冒烟（基线态：双开关关闭）

`scripts/global_smoke.py` → **32 passed, 0 failed**。
（首跑暴露真机库缺 0008 迁移——`app.db.migrate` 补齐后复跑全绿；
迁移欠账已记入报告第五节。）

## 三、真机彩排

**基线态（双开关关闭）**：P1 陈晨(CN 后端)/P2 李悦(UK 需签证)/P3 王铭
(金融转数据) 全 completed 且国别、demo 标记、警告位全对 → **3/3 PASS**；
P4 正确打印 SKIP（开关关闭）——关闭态主线零回归。

**开启态（终局切换：RESUME_CLARIFY_ENABLED + CONSULT_COACH_ENABLED）**：
**4/4 PASS**。
- P1–P3 在开启态下不受影响（等价性的真机侧证据）；
- P4 林安·简历含糊者（session `4f3745bf-…`, run `6817adae-…`；单跑
  session `8da69c3e-…`, run `98c9c867-…`）关键断言：
  - r4 进 resume_clarify 并针对含糊经历发问；
  - r5 实质回答 → `C001` span，**span.text 与用户原话逐字相等**
    （"我曾使用 Python、pandas 和 SQL 清洗 12,480 条销售记录，并把每周
    仪表盘刷新时间缩短了 31%。"，source=user_clarification）；
  - r6 跳过 → targets 耗尽，PM note trigger=**finalizable**（verdict=advise，
    文案基于真实 state 事实）；
  - r7 首入 deepen → PM note trigger=**deepen_entry**（verdict=pass）；
  - r2 已出 **stagnation** note——三类触发按 stagnation→finalizable→
    deepen_entry 顺序各一次，**教练预算恰好 3/3 耗尽**，verdict 三条
    双落 supervisor_log；
  - r8 finalize→match-brief→execute→completed，5 个 UK 岗位，
    **公开 run result 证据链引用 C001**；
  - 匹配后简历确认状态保持 current（version=1 confirmed=1）。

## 四、配置快照（无秘密）

RAPTOR_ENABLED=true；RERANK_ENABLED=true（gte-rerank-v2 经典公网端点）；
RESUME_CLARIFY_ENABLED=true，RESUME_CLARIFY_MAX=2；
CONSULT_COACH_ENABLED=true，CONSULT_COACH_MAX=3（终局切换已固化 .env）；
AUTH_ENFORCED=true；EMAIL_OTP_PROVIDER=smtp（演示彩排期用 console）；
SESSION_QUOTA_PER_USER=3；PostgreSQL 17 + pgvector vector(1024)；
DeepSeek V4 flash/pro + Qwen text-embedding-v4。

## 五、批次 9 期间发现并即修的两项

1. **真机库迁移欠账**：0008 只在 5A 的一次性验证库跑过，演示库未升——
   `python -m app.db.migrate` 补齐（运维口径：部署/演示前跑 migrate，
   已在 known_issues 运维备忘中体现）；
2. **rehearsal 脚本 sys.path 自足性**：p4_switch_status 导入 app.config
   前注入仓库根，任意 CWD 可直跑。

## 六、结论

批次 9 总验收 **通过**。产品行为代码与实测工件自本报告起**冻结**
（W-C 文档阶段允许新增文档与文档工具脚本，禁触行为面）。
