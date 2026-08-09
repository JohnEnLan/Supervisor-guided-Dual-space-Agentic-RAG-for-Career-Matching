# 部署指南：zhangen.cn @ 45.153.131.127（香港 · Ubuntu 22.04）

> 所有「本机」命令在你 Windows 的 PowerShell 里跑；所有「服务器」命令是
> SSH 登进去之后贴。配套文件在 `deploy/`。
> 上传包由 Claude 预先在本机生成（第 2 步）。
> **2026-08-08 实战定稿**：本指南已按首次真实部署踩坑修订，与线上环境一致。

## 跨境连接三条铁律（实战教训）

1. **连接一律带心跳**，否则长命令中途会被掐线：
   ```bash
   ssh -o ServerAliveInterval=15 -o ServerAliveCountMax=6 root@45.153.131.127
   ```
2. **大文件切块传**：901MB+ 的 dump 直传曾在 63% 断掉。按 100MB 切块逐个 scp，
   断了只补缺块；服务器上 `cat dump.part* > career_rag.dump` 拼回并 `sha256sum` 比对。
3. **长任务放后台**：SSH 一断，前台进程会被杀（pg_restore 曾因此留下半截库）。
   凡是要跑几分钟以上的命令都用 `nohup ... > xxx.log 2>&1 &`，进度看 log。

## 第 0 步：两项前置（各一分钟）

1. **域名解析**：到域名控制台（购买 zhangen.cn 的地方）→ 解析设置 → 加两条记录：
   - 类型 `A`，主机记录 `@`，记录值 `45.153.131.127`
   - 类型 `A`，主机记录 `www`，记录值 `45.153.131.127`

   `.cn` 域名必须完成**实名认证**才会生效（一般买时已做；没做的话解析会被
   注册局暂停，控制台会有提示）。指向香港服务器**不需要备案**。
2. **确认系统**：服务器控制台看镜像是否 Ubuntu 22.04；若是默认的 CentOS 7.6，
   先「重装系统」换 Ubuntu 22.04 再继续。

## 第 1 步（服务器）：初始化

```bash
ssh root@45.153.131.127
```

登进去后建目录；若买了独立数据盘（`lsblk` 里有一块无挂载点的空盘，如 40G 的 `vdb`），
先格式化并挂到应用目录（**仅对全新空盘执行**，mkfs 会清空整块盘）：

```bash
mkdir -p /opt/career-rag
lsblk    # 确认 vdb 存在且无分区、无挂载点
mkfs.ext4 /dev/vdb
mount /dev/vdb /opt/career-rag
echo "UUID=$(blkid -s UUID -o value /dev/vdb) /opt/career-rag ext4 defaults 0 2" >> /etc/fstab
df -h /opt/career-rag    # 应显示约 40G 可用
```

## 第 2 步（本机）：上传部署包

Claude 已在本机生成三个文件（位于 `tmp\deploy_out\`）：
- `app.tar.gz` —— 代码快照（git archive，不含 .venv/node_modules）
- `frontend-dist.tar.gz` —— 前端构建产物
- `career_rag.dump` —— 数据库全量导出（含全部向量，服务器上**不需要**重跑 embedding）

PowerShell 上传（约 5–15 分钟，视上行带宽）：

```bash
scp "tmp\deploy_out\app.tar.gz" "tmp\deploy_out\frontend-dist.tar.gz" "tmp\deploy_out\career_rag.dump" "deploy\server_setup.sh" "deploy\Caddyfile" "deploy\career-rag.service" "deploy\env.production.template" root@45.153.131.127:/opt/career-rag/
```

## 第 3 步（服务器）：跑初始化脚本

```bash
cd /opt/career-rag && bash server_setup.sh
```

结束时会打印一行 **数据库密码**——复制下来，下一步要用。

## 第 4 步（服务器）：解包应用 + 配置

```bash
cd /opt/career-rag
useradd -r -m -s /bin/bash career 2>/dev/null || true
mkdir -p app releases/frontend-initial
tar -xzf app.tar.gz -C app
tar -xzf frontend-dist.tar.gz -C releases/frontend-initial
ln -sfn /opt/career-rag/releases/frontend-initial /opt/career-rag/frontend-current
cp env.production.template app/.env
nano app/.env    # 按模板注释逐项填：DB 密码、各 API key、新 JWT 秘钥、QQ 授权码
```

> 前端采用 **releases 版本目录 + `frontend-current` 符号链接** 布局
> （B2 起，Caddyfile 的 root 指向 frontend-current）：每次发版解包到
> `releases/frontend-<版本>` 新目录，再原子翻链切换，无 404 窗口、可秒回滚。

Python 环境：

```bash
python3.11 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r app/requirements.txt
chown -R career:career /opt/career-rag
```

## 第 5 步（服务器）：导入数据 + 迁移

```bash
cd /opt/career-rag && nohup sudo -u postgres pg_restore -d career_rag --no-owner --role=career -j 2 career_rag.dump > restore.log 2>&1 &
```

后台跑（断线不死），进度与完成判断：

```bash
tail /opt/career-rag/restore.log; ps aux | grep [p]g_restore
sudo -u postgres psql -c "SELECT pg_size_pretty(pg_database_size('career_rag'));"
```

进程消失 + 库约 2.5GB + log 末尾 `errors ignored on restore: 1` ＝ 成功
（那 1 条是 `COMMENT ON EXTENSION vector` 权限提示，无害；后台任务因此
显示 `Exit 1` 也正常）。然后跑迁移：

```bash
sudo -u postgres psql -d career_rag -c "REASSIGN OWNED BY postgres TO career;" 2>/dev/null || true
cd /opt/career-rag/app && sudo -u career ../venv/bin/python -m app.db.migrate
```

migrate **静默退出即成功**——注意它**无论是否应用了新迁移都不打印**
（B3 部署时实证），所以"有无生效"以查询为准：
`sudo -u postgres psql -d career_rag -c "SELECT name FROM schema_migrations ORDER BY applied_at DESC LIMIT 3;"`。
若需重来（如断线留下半截库）：`DROP DATABASE career_rag;` 后按 setup 脚本第 4 步
重建空库（CREATE DATABASE / EXTENSION vector / ALTER SCHEMA），再重新 restore。

## 第 6 步（服务器）：服务上线

```bash
cp /opt/career-rag/career-rag.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now career-rag
systemctl status career-rag --no-pager    # 应显示 active (running)
# 应用初始化（连库、装配编排图）约需 5–20 秒，刚起来时 curl 可能空响应，稍等重试：
curl -s http://127.0.0.1:8000/api/v1/capabilities    # 吐 JSON 即后端就绪

cp /opt/career-rag/Caddyfile /etc/caddy/Caddyfile
systemctl reload caddy
```

Caddy 会在域名解析生效后**自动申请 HTTPS 证书**（首次访问约几秒）。

## 升级部署（B2 起的标准顺序，含前后端契约变更时）

顺序写死：**后端先行，前端后切**（反过来会让新前端撞上旧后端的自动解析，
绕过确认制烧钱）：

```bash
# ① 后端：解包 → 补依赖/配置 → 重启 → 健康检查
cd /opt/career-rag && tar -xzf app.tar.gz -C app && chown -R career:career app

# B4 新增 pypdfium2/Pillow；已有环境重复执行无害。
# 若已 cd 到 app，等价命令是 ../venv/bin/pip install -r requirements.txt
sudo -u career ./venv/bin/pip install -r app/requirements.txt

# B4 的 8 个 OCR 变量**一次性**追加（幂等守卫：已有该键就整段跳过——
# dotenv 重复键后值胜出，盲目重复追加会静默覆盖你手动调过的值，比如
# 回滚时设的 RESUME_OCR_ENABLED=false）；printf 开头保留换行防连行
grep -q '^RESUME_OCR_ENABLED=' app/.env || printf '\n%s\n' \
  'RESUME_OCR_ENABLED=true' \
  'QWEN_VL_MODEL=qwen-vl-ocr' \
  'VL_MAX_CONCURRENCY=2' \
  'RESUME_OCR_PAGE_MIN_CHARS=50' \
  'RESUME_OCR_MAX_PAGES=6' \
  'RESUME_OCR_MAX_PIXELS=4000000' \
  'RESUME_OCR_RENDER_SCALE=2.0' \
  'RESUME_OCR_MAX_IMAGE_PIXELS_DECODE=40000000' \
  >> app/.env

# B4 功能回滚（不换包）：把 .env 里 RESUME_OCR_ENABLED 改为 false →
# systemctl restart career-rag → 校验 capability 具体值为 false：
#   curl -s http://127.0.0.1:8000/api/v1/capabilities | grep -o '"resume_image_upload_enabled":[a-z]*'
# 开关关闭后图片上传回到 415；OCR 开启期已上传未解析的图片，确认解析会
# 得到 409 resume_ocr_disabled（不扣额度），引导用户重传文字版。

# 本批无需 migrate（B4 未新增数据库迁移）
# B5 必须应用 0011；migrate 静默退出仍是正常语义，以 schema_migrations 为准。
(cd /opt/career-rag/app && sudo -u career ../venv/bin/python -m app.db.migrate)
sudo -u postgres psql -d career_rag -c \
  "SELECT name, applied_at FROM schema_migrations WHERE name = '0011_llm_usage_and_product_events.sql';"

# B5 的管理员邮箱与三个开关逐键幂等追加；执行前替换邮箱占位符。
# 分别守卫可兼容“已有 ADMIN_EMAILS、尚无三个 flag”的增量环境；若已有
# ADMIN_EMAILS 空行，直接编辑该行，守卫不会覆盖现值。
grep -q '^ADMIN_EMAILS=' app/.env || printf '\n%s\n' \
  'ADMIN_EMAILS=<<管理员登录邮箱>>' >> app/.env
grep -q '^EVALUATION_CAPABILITY_ENABLED=' app/.env || printf '%s\n' \
  'EVALUATION_CAPABILITY_ENABLED=true' >> app/.env
grep -q '^MONITORING_ENABLED=' app/.env || printf '%s\n' \
  'MONITORING_ENABLED=true' >> app/.env
grep -q '^MONITORING_ADMIN_MODE=' app/.env || printf '%s\n' \
  'MONITORING_ADMIN_MODE=true' >> app/.env

# ADMIN_EMAILS 与三个 flag 都由进程启动时的 settings 读取，改完必须重启。
systemctl restart career-rag && sleep 8
curl -s http://127.0.0.1:8000/api/v1/capabilities   # 吐 JSON 才继续

# ② 前端：解包到新 release 目录 → 原子翻链（rename，无空窗）
REL=/opt/career-rag/releases/frontend-$(date +%Y%m%d%H%M)
mkdir -p "$REL" && tar -xzf /opt/career-rag/frontend-dist.tar.gz -C "$REL"
ln -sfn "$REL" /opt/career-rag/current.tmp
mv -Tf /opt/career-rag/current.tmp /opt/career-rag/frontend-current

# ③ Caddyfile 有变更时：先校验再热加载
cp /opt/career-rag/Caddyfile /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy
```

### B5 运维手册

- `ADMIN_EMAILS` 是启动时加载的配置；增加或移除邮箱后必须重启
  `career-rag` 才生效。新增管理员在重启后用白名单 email 重新登录，登录事务
  才会同步 `is_admin`；移除并重启后，该账号下一次管理员请求返回 403。
- 管理员必须使用 email OTP 登录；phone 会话、旧 token 缺少 `idp`、数据库
  `is_admin=false`、或账号没有任一邮箱身份命中白名单，都会 fail-closed。
- 解析额度 reset 端点只把 `resume_parse_count` 清零；若命中重启遗留的
  `resume_queued`，还会置 `resume_error` 并清上传内容，**端点本身从不重排队**。

**B3 红线（原文收录）**：若未来任何救济路径把**同一代**重新置回
`resume_queued`（当前端点不这么做；正常流每代至多一次入队），必须连带
`DELETE FROM resume_intake_progress WHERE session_id=$1 AND generation=$2`——
该代曾达终态时残留的 `seq=100` 行会让新任务的终态 CAS 永久回滚、mark 兜底
同撞 PK，会话卡死在 queued。

**break-glass（管理员通道恢复/紧急撤权）**——注意：`require_admin` 每请求
都要求"email 登录票 + 数据库 `is_admin` + 邮箱命中 `ADMIN_EMAILS`"三者
同时成立，且每次 email 登录事务会按白名单**重算** `is_admin`。因此：

- **恢复/授予管理员（唯一有效路径）**：把该邮箱加入 `.env` 的
  `ADMIN_EMAILS`（逗号追加）→ `systemctl restart career-rag` → 该用户用
  email OTP **重新登录**（登录事务自动置 `is_admin=TRUE` 并递增
  `token_version`，无需任何 SQL）。事后若是临时授权，记得从白名单移除
  并再重启。**单独执行 `UPDATE users SET is_admin=TRUE` 无效**：白名单
  不含该邮箱时请求仍 403，且下一次登录会把布尔列重算回 FALSE。
- **紧急撤权（立即生效）**：先从 `ADMIN_EMAILS` 移除并重启（持久化，
  下一请求 403），如需立刻踢掉在票会话再补一条 SQL——直接改
  `users.is_admin` 时必须在**同一条 UPDATE** 同步递增 `token_version`，
  使旧票下一请求 401，不要只改布尔列：

```sql
UPDATE users
SET is_admin = FALSE, token_version = token_version + 1
WHERE user_id = '<<user_uuid>>'::uuid;

-- 紧急吊销全部在票会话（所有账号都需重新登录）：
UPDATE users SET token_version = token_version + 1;
```

已打开的旧标签页刷新即恢复（index.html 为 no-store，新访客即刻拿新版）。
若必须回滚 B2 到旧包：**先** `systemctl stop career-rag`，再执行
`deploy/rollback_b2.sql`（见文件头注释的四步顺序），换包后 start。

## 第 7 步：验证

浏览器打开 `https://zhangen.cn` → 登录页 → 邮箱验证码 → 完整走一遍
上传简历 → 咨询 → 匹配。接口健康检查：

```bash
curl -s https://zhangen.cn/api/v1/capabilities
```

## 故障排查速查

| 现象 | 看哪里 |
|---|---|
| 后端起不来 | `journalctl -u career-rag -n 50 --no-pager` |
| HTTPS 没生效 | `journalctl -u caddy -n 30`；先确认 `ping zhangen.cn` 已解析到服务器 IP |
| 数据库连不上 | `.env` 里 DATABASE_URL 密码是否为 setup 脚本打印的那个 |
| 验证码收不到 | QQ 授权码是否填对；`journalctl -u career-rag` 里搜 smtp |

## 安全备忘

- root 密码只存你自己的密码管理器；建议上线稳定后 `ssh-keygen` 换密钥登录并关密码登录；
- `AUTH_JWT_SECRET` 必须是服务器上新生成的，不要复用本机开发值；
- QQ SMTP 授权码答辩前轮换（既有备忘）。
