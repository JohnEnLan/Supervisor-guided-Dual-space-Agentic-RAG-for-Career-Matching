# 账号体系技术书：Google 登录 / 微信扫码 / 手机验证码

> 目标读者：后续要给本项目加注册登录的你。
> 现状：系统没有账号体系——前端直接把 `user_id` 传给后端。本文给出在**现有 FastAPI + PostgreSQL + asyncio** 架构上落地三种注册/登录方式的完整设计，按阶段可各自独立上线。

---

## 0. 总体设计（先定骨架，三种方式只是插件）

### 0.1 核心原则：账号与"登录方式"分离

一个用户（`users` 表一行）可以绑定多种登录方式（`user_identities` 表多行）。Google、微信、手机号都只是**身份凭证提供方**，注册=第一次用某凭证登录时自动建号。这样将来加 GitHub、邮箱密码都不用改骨架。

### 0.2 表设计（加两张主表 + 一张验证码表）

```sql
CREATE TABLE users (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name  TEXT,
    avatar_url    TEXT,
    status        TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active','banned','deleted')),
    token_version INTEGER NOT NULL DEFAULT 0,   -- 封禁/改密时 +1，旧 Cookie 立即失效
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE user_identities (
    identity_id   BIGSERIAL PRIMARY KEY,
    user_id       UUID NOT NULL REFERENCES users(user_id),
    provider      TEXT NOT NULL CHECK (provider IN ('google','wechat_union','wechat_app','phone')),
    provider_uid  TEXT NOT NULL,
    -- google        → sub
    -- wechat_union  → unionid（跨应用稳定键）
    -- wechat_app    → appid || ':' || openid（应用内键，必须带 AppID 命名空间）
    -- phone         → E.164 手机号
    raw_profile   JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ,
    UNIQUE (provider, provider_uid)
);
CREATE INDEX idx_identities_user ON user_identities(user_id);

CREATE TABLE phone_otp (
    id            BIGSERIAL PRIMARY KEY,
    phone         TEXT NOT NULL,              -- E.164 格式 +8613800000000
    client_ip     INET,                       -- 发送请求来源，供 IP 限流
    code_hash     TEXT NOT NULL,              -- HMAC-SHA256(key=OTP_PEPPER, message=phone||purpose||code)
                                              -- pepper 是服务端独立密钥（.env 不落库，可轮换）；
                                              -- 6 位码空间只有 10^6，库内加盐哈希挡不住穷举，必须靠库外 pepper；
                                              -- 比对用 hmac.compare_digest 常量时间比较。
    purpose       TEXT NOT NULL DEFAULT 'login' CHECK (purpose IN ('login','bind')),
    expires_at    TIMESTAMPTZ NOT NULL,       -- 建议 5 分钟
    attempts      INT NOT NULL DEFAULT 0,     -- 校验失败次数，≥5 作废
    consumed_at   TIMESTAMPTZ,                -- 用过即焚
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_otp_phone ON phone_otp(phone, created_at DESC);
CREATE INDEX idx_otp_ip ON phone_otp(client_ip, created_at DESC);
```

**微信双键说明**：同一用户先以 `wechat_app`（appid:openid）登录、之后拿到 unionid 时，要在同一事务里把 `wechat_union` 身份**关联到已有账号**（而不是新建账号）；合并规则：查 `wechat_app` 已存在 → 给该 user 追加 `wechat_union` 行。UnionID 的作用域是"同一微信开放平台账号下的所有应用"。

**与现有系统的接合点（关键，分两步，都不能省）**：

第一步：user_id 不再由前端传，从登录态解析：

```python
# app/api/auth/deps.py
SESSION_COOKIE = "__Host-app_session"   # __Host- 前缀要求：Secure、Path=/、不设 Domain

async def current_user(request: Request) -> AuthedUser:
    token = request.cookies.get(SESSION_COOKIE)
    payload = verify_session_token(token)          # 签名/过期不合法 → 401
    user = await load_user(payload["user_id"])
    if (
        user is None
        or user.status != "active"                          # 封禁/注销立即失效
        or user.token_version != payload["token_version"]   # 强制踢人/改密后旧 Cookie 作废
    ):
        raise HTTPException(401)
    return user
```

第二步（**资源级授权，最容易漏也最致命**）：当前所有 session/run/feedback 路由只凭 `session_id`/`run_id` 就能读写资源——登录后如果不校验"这个资源属于当前用户"，任何登录者拿到别人的 ID 就能读别人的简历和结果。必须：

- `session_state` 已有 user_id 列，`match_runs` 经 session 关联到 user——每条 session/run/feedback 路由（含旧 API）在取资源后**校验属主**，不匹配统一返回 404（不是 403，避免泄露资源存在性）；
- 落地方式：一个 `require_owned_session(session_id, user)` / `require_owned_run(run_id, user)` 依赖，全部路由套用；
- 补授权测试：A 用户的 Cookie 访问 B 用户的 session/run → 404。

### 0.3 登录态：无状态服务怎么"记住"用户

沿用本项目"无状态进程"的铁律，登录态放**签名 Cookie**（不放服务器内存）：

- 登录成功后签发 `__Host-app_session` Cookie（`__Host-` 前缀强制 Secure+根路径+不带 Domain，防子域注入）：内容 `{user_id, exp, jti, token_version}`，用 `AUTH_SECRET_KEY` 做 HMAC 签名（JWT HS256 即可，PyJWT 库）；
- Cookie 属性：`HttpOnly` + `Secure` + `SameSite=Lax`；
- **CSRF 防护不能只靠 SameSite**（它是纵深防御不是主防线，OWASP 明确不推荐单独依赖）：所有状态变更请求（POST/PUT/PATCH/DELETE）后端校验 `Origin`/`Referer` 头必须等于本站精确 origin；前后端跨源部署时再加双提交 CSRF token；
- 有效期建议 7 天，前端无感续期：过半自动换新；
- 登出=清 Cookie；强制踢人/封禁即时生效靠两件事：每次鉴权查 `users.status`（见上）+ `users` 表加 `token_version` 整数，封禁或改密时 +1，token 里的版本号对不上即失效。

### 0.4 统一登录完成函数（三种方式殊途同归）

```python
async def login_or_register(provider: str, provider_uid: str, profile: dict) -> str:
    """查 user_identities：有 → 返回 user_id；没有 → 开事务建 users + identities。
    并发安全靠 UNIQUE(provider, provider_uid)，撞了就重查。"""
```

---

## 1. Google 注册/登录（OAuth 2.0 + OIDC，授权码模式）

### 1.1 流程（时序）

```
浏览器                     本系统后端                        Google
  │ 点击"用 Google 登录"        │                               │
  ├──────────────────────────→ │ GET /api/v1/auth/google/start │
  │                            │ 生成 state + PKCE(code_verifier/challenge) + nonce
  │                            │ 三者一起存签名临时 cookie（10 分钟 TTL，单次使用）│
  │ ←── 302 跳转到 Google ──────┤                               │
  ├──── 用户在 Google 同意授权 ──────────────────────────────────→│
  │ ←── 302 回调 /auth/google/callback?code=..&state=.. ─────────┤
  ├──────────────────────────→ │ 校验 state ↔ cookie 一致       │
  │                            │ 拿 code+code_verifier 换 token ├──→ token 接口
  │                            │ 校验 id_token(JWT)：签名/iss/aud/exp/nonce
  │                            │ 校验通过后立即作废临时 cookie（防重放）
  │                            │ 取 sub(用户唯一ID)+email+name  │
  │                            │ login_or_register('google', sub, profile)
  │ ←── 签发 __Host-app_session Cookie，302 回前端 /workspace ───┤
```

### 1.2 落地要点

- **Google Cloud Console** 建 OAuth Client（Web application），配置授权回调 `https://你的域名/api/v1/auth/google/callback`；本地开发加 `http://localhost:8000/...`。
- 请求 scope 只要 `openid email profile`，够用就别多要。
- **授权事务三件套绑定**（state / PKCE code_verifier / OIDC nonce）：三者在 `/start` 时一次性生成，一起放进一个**短 TTL（10 分钟）、单次使用**的签名临时 Cookie（或服务端表），回调时校验 state 一致、用 code_verifier 换 token、校验 id_token 里的 nonce 等于预期值，然后**立即作废**该事务（删 Cookie/删行），防重放。声称校验 nonce 就必须在授权请求里真的发送它。
- **id_token 验签用 `google-auth` 库**（自动处理 JWKS、签名、`aud`、`exp` 与 issuer——注意现代 issuer 是 `https://accounts.google.com`，旧实现可能无 scheme，手写单一字符串比对会翻车，所以别手写）。库的分工：`google-auth` 只管 Google 的 id_token，本站自己的 session Cookie 仍用 `PyJWT` 签发/校验——两个库都要装，不是二选一。
- 账号键用 **`sub`**（永不变），不要用 email 当主键（用户可改邮箱）。
- 依赖：`httpx`（已有）+ `google-auth`（验 Google id_token）+ `PyJWT`（签发/校验本站 session Cookie）——三者都要，不是二选一。

### 1.3 接口

| 路由 | 作用 |
|---|---|
| `GET /api/v1/auth/google/start` | 生成 state/PKCE，302 到 Google |
| `GET /api/v1/auth/google/callback` | 换 token、验 id_token、登录建号、签 Cookie |

---

## 2. 微信扫码注册/登录（开放平台·网站应用）

### 2.1 前置条件（比写代码更花时间，先办）

- 注册**微信开放平台**（open.weixin.qq.com）账号并完成**开发者资质认证**（需要企业主体，个人不行）；
- 创建"网站应用"，审核通过后拿到 `AppID/AppSecret`，配置授权回调域名。
- 学生项目如果没有企业主体：可在论文里写设计+用沙箱演示，或退而用"公众号测试号 H5 授权"演示流程（非扫码但协议同构）。

### 2.2 流程（时序，本质也是 OAuth 授权码，只是入口是二维码）

```
浏览器                          本系统后端                        微信
  │ 点击"微信扫码登录"              │                               │
  ├────────────────────────────→ │ GET /auth/wechat/start        │
  │ ←─ 302 到 open.weixin.qq.com/connect/qrconnect?appid=..&state=.. ─┤
  │    （页面显示二维码）            │                               │
  ├── 用户手机微信扫码并确认 ─────────────────────────────────────────→│
  │ ←─ 302 回调 /auth/wechat/callback?code=..&state=.. ──────────────┤
  ├────────────────────────────→ │ 校验 state                     │
  │                              │ code 换 access_token+openid    ├──→ /sns/oauth2/access_token
  │                              │ （若有 unionid 优先用 unionid）  │
  │                              │ 需要昵称头像再调 /sns/userinfo   │
  │                              │ resolve_wechat_identity(appid, openid, unionid, profile)
  │                              │   （见 §2.3：双键解析，不是二选一）│
  │ ←── 签发 __Host-app_session Cookie ┤                          │
```

### 2.3 落地要点

- **unionid vs openid**：openid 是"用户×应用"维度（不同 App 不同值，必须带 AppID 命名空间存储）；unionid 是"用户×同一开放平台账号下所有应用"维度。**双键分开存**（`wechat_app` = appid:openid，`wechat_union` = unionid，见 §0.2 表设计）。`resolve_wechat_identity` 的完整解析顺序（单事务内，**先把两种身份一次性都查出来，再按序判定**——冲突检查必须排第一，否则会被前面的分支截获、撞唯一约束）：
  1. **冲突分支优先**：`wechat_union` 与 `wechat_app` 都存在且属主是两个不同 user → 不执行任何绑定，登录到 unionid 所属账号并标记冲突待人工/绑定页处理——账号数据合并（简历、反馈的归并）是产品决策，必须显式设计，不能靠 UNIQUE 撞库后重查糊过去；
  2. 仅 `wechat_union` 存在 → 返回其 user，补绑本次的 `wechat_app` 身份；
  3. 仅 `wechat_app` 存在 → 返回其 user，有 unionid 就补写 `wechat_union` 行；
  4. 两者都不存在 → 建新 user + 双身份行。
- 微信 access_token 用完即弃，**不要**存库当登录态——登录态统一走我们自己的 Cookie。
- state 同样必须校验；微信回调只支持 HTTP 302 方式，前后端分离时回调落在后端再 302 回前端。
- 错误处理：用户扫码后取消（回调带 `state` 无 `code`）→ 回登录页并提示。

---

## 3. 手机验证码注册/登录（SMS OTP）

### 3.1 流程

```
① POST /auth/phone/send-code {phone}
     校验手机号格式(E.164) → 三级限流检查（见 §3.2，锁内原子）
     → 用 CSPRNG 生成 6 位码（Python secrets.randbelow，禁用 random 模块）
     → 存 phone_otp(code_hash, 5min 过期) → 调短信服务商发送
     → 返回 202（不论号码是否已注册，响应一致，防号码探测）
② POST /auth/phone/verify {phone, code}
     单事务内：SELECT ... FOR UPDATE 锁定该号码最新未消费记录
     → attempts+1 → 比对 HMAC 哈希 →
        对：条件 UPDATE 标记 consumed（WHERE consumed_at IS NULL，抢不到即已被并发消费→401），
            login_or_register('phone', phone, {})，签 Cookie
        错：401；attempts≥5 该码作废；过期：410 提示重发
     （锁行 + 条件更新缺一不可：否则并发 verify 能重复消费同一码或突破 5 次上限）
```

### 3.2 防刷设计（验证码系统的生死线）

| 层 | 措施 |
|---|---|
| 发送频率 | 同号码 60 秒 1 条、1 小时 5 条、24 小时 10 条 |
| IP 限流 | 同 IP 每小时 ≤20 次（`client_ip` 必须从**可信反向代理链**解析——只信自己代理追加的那一跳，不直接信任意 `X-Forwarded-For`；解析不到 IP 时按最严限流处理，不得静默放行） |
| 全局预算 | 每日全局短信条数上限 + 服务商侧消费封顶，防分布式号码轰炸把账单打爆 |
| **原子性** | 三级限流各自要原子：advisory lock 按 key 排他，`lock(hashtext(phone))` 只能串行同号码，管不住"同 IP 打不同号码"和全局额度。正确做法：phone / ip / global 三个**固定命名空间**的 `pg_advisory_xact_lock(namespace, hash)` 按固定顺序（global→ip→phone）获取后再"查计数+插入"；或改用三张原子 UPSERT 计数桶表 |
| 人机校验 | 发送前加图形验证码/滑块（前端接 hCaptcha 或自建，第一版可后置） |
| 校验爆破 | 单条码错 5 次作废；verify 接口同号码每分钟 ≤10 次——注意 `phone_otp.attempts` 只是累计数，算不出"每分钟"窗口，需另建 verify 尝试记录表或时间桶计数表 |
| 存储 | 只存 HMAC-pepper 哈希；用后即焚；过期行由**独立的 lifespan 周期任务**清理（不能挂在现有 checkpoint 清理任务上——那个任务只在启用 LangGraph 时才创建；OTP 清理必须无条件运行，或交给数据库定时任务） |

### 3.3 短信服务商

国内：阿里云短信/腾讯云 SMS（需备案签名+模板，个人可申请）；海外/演示：Twilio Verify（免签名模板，还替你管验证码生命周期，学生项目**推荐直接用 Twilio Verify**——但注意即便验证码生命周期外包了，**本地限流计数表仍然要留**：IP/号码/全局预算限流是我们自己的责任，不能随 `phone_otp` 一起省掉）。开发阶段可设 `SMS_PROVIDER=console` 联调，但有硬性限制：**仅限 development/test 环境启用（生产配置必须禁止）、只允许测试号段、且验证码输出违反"OTP 不写日志"的一般原则**——它存在的唯一理由是本地零成本联调，上线前必须移除。

---

## 4. 前端改动

- 新增 `/login` 页：三个按钮（Google / 微信 / 手机号表单）+ 验证码倒计时组件；
- 全局请求带 Cookie（`credentials: 'include'`），401 统一跳 `/login`；
- 现有页面把"手填 user_id"的入口移除；`NewSessionPage` 创建会话不再传 user_id（后端从 Cookie 取）；
- 顶栏加头像/昵称 + 登出；
- **监控页访问策略要重新定级**：现有 `/monitoring/runs` 返回全局最近运行列表，账号上线后它就是跨用户数据——必须明确它是管理员/答辩演示能力（加角色位或独立开关），不能默认对所有登录用户开放。

## 5. 配置清单（.env 增量）

```
AUTH_SECRET_KEY=<32+字节随机串>          # Cookie 签名
OTP_PEPPER=<32+字节随机串>               # 验证码 HMAC 密钥（独立于 AUTH_SECRET_KEY，可轮换）
AUTH_SESSION_TTL_DAYS=7
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://host/api/v1/auth/google/callback
WECHAT_APP_ID=...
WECHAT_APP_SECRET=...
WECHAT_REDIRECT_URI=...
SMS_PROVIDER=console|twilio|aliyun
TWILIO_ACCOUNT_SID=... / TWILIO_VERIFY_SERVICE_SID=...   # 按服务商
```

## 6. 分阶段实施建议

| 阶段 | 内容 | 工作量估计 |
|---|---|---|
| P0 | 骨架：users/user_identities 表 + Cookie 会话 + `current_user` 依赖 + **全部 session/run/feedback 路由的资源属主校验（含旧 API）与授权测试** + 登录页壳 | 2 天 |
| P1 | 手机验证码（console 模式起步，最容易端到端跑通） | 1 天 |
| P2 | Google 登录（有国际化演示价值，流程标准） | 1 天 |
| P3 | 微信扫码（先办资质！代码半天，审核以周计） | 资质周期为主 |
| P4 | 加固：图形验证码、账号绑定页（注意：绑定流程上线**之前**，同一个人用 Google 和手机分别登录会得到两个账号——表结构支持绑定不等于产品已支持，需在 UI 提示）、账号注销与数据删除联动 | 1–2 天 |

## 7. 安全红线清单（照抄执行）

1. **资源级授权是第一红线**：每条按 session_id/run_id 取资源的路由（含旧 API）必须校验属主，不匹配一律 404；上线前必须有"A 的 Cookie 访问 B 的资源 → 404"测试。
2. 所有 OAuth 流程校验 `state`；Google 再加 PKCE 与 nonce，三者绑定同一短 TTL 单次事务；id_token 用 `google-auth` 验签（不手写 issuer 比对）。
3. 验证码：HMAC-pepper 哈希（pepper 在 .env、可轮换）、5 分钟过期、锁行+条件更新原子消费、错 5 次作废、号码/IP/全局三级限流且计数原子化。
4. Cookie：`__Host-` 前缀 + HttpOnly + Secure + SameSite=Lax，另加 Origin/Referer 校验（SameSite 只是纵深防御）；跨源部署再加 CSRF token 与精确 origin 的 CORS（`allow_credentials` 只对白名单 origin）。
5. 任何"发送验证码/是否已注册"接口的响应不得泄露号码是否存在；OTP 不写日志（console 联调模式仅限开发环境）。
6. 第三方 access_token 不落库、不返回前端；我方登录态与第三方令牌完全解耦。
7. 封禁/注销即时生效：每次鉴权查 `users.status` + `token_version` 比对，不依赖 Cookie 自然过期。
8. 账号删除需要一次**迁移**（现有 `session_state/private_memory/feedback_memory.user_id` 是 TEXT 且无外键指向 `users`）和明确的删除顺序：checkpoint 三表（按 run_id）→ run events/metrics/runs → session_state → private_memory/feedback_memory → user_identities → users；历史随机 user_id 的数据按"无主数据保留期"策略单独处理。
