# 给 AI 协作者的部署说明：「上传服务器」到底是什么意思

> 用户说「上传到服务器」「部署」「上线」「发布到 zhangen.cn」时，
> 指的都是同一件事。本文定义这件事的确切含义与分工。
> 详细命令的权威出处是 `docs/deploy_guide.md`；本文是概念与流程速通。

## 1. 一句话定义

把**本机已通过验收门的代码**打成两个压缩包，交给**用户本人**用
scp/ssh 放到香港生产服务器上解包生效，让 https://zhangen.cn 跑上新版。

代码推到 GitHub/GitLab **不等于**部署——远端仓库只是代码备份，
生产服务器不会自动拉取。部署是一个独立的手工动作。

## 2. 生产环境长什么样

| 项 | 值 |
|---|---|
| 域名 | https://zhangen.cn （Caddy 反代 + 自动 HTTPS） |
| 服务器 | 45.153.131.127，Ubuntu 22.04，root 登录 |
| 后端 | `/opt/career-rag/app`（代码）+ `/opt/career-rag/venv`，systemd 服务名 `career-rag`，监听 127.0.0.1:8000 |
| 前端 | 静态产物放 `/opt/career-rag/releases/frontend-<时间戳>/`，软链 `/opt/career-rag/frontend-current` 指向当前版；Caddy 从软链目录发文件 |
| 数据库 | 同机 PostgreSQL（career_rag 库，含 pgvector） |

## 3. 分工红线（最重要的一节）

- **AI（你）负责**：① 确认验收门全绿；② 在本机打两个包；
  ③ 把可直接粘贴的命令打印给用户；④ 部署后用公网 URL 验证结果。
- **用户负责**：执行所有 scp/ssh 命令。**服务器密码只在用户手里，
  你永远不碰凭据、永远不自己连服务器。** 你的工作在「打印命令」处
  结束，在「用户贴回终端输出」或「公网验证」处恢复。
- 你**可以**做的远程动作只有一种：对公网只读端点发 GET 验证
  （见 §6），因为它不需要凭据。

## 4. 部署前：你在本机要做的事

```powershell
# 0) 先按 HANDOFF §3.1 核对冻结验收记录，并跑当前运行时发布门，然后在项目根目录：
git archive --format=tar.gz -o app.tar.gz HEAD          # 后端源码包
cd frontend; npm run build; cd ..
tar -czf frontend-dist.tar.gz -C frontend/dist .        # 前端产物包
```

注意：`frontend-dist.tar.gz` 的归档根必须直接是 dist 内容
（`./index.html` 在顶层），不能多包一层 dist/ 目录。

## 5. 部署命令：打印给用户执行

判定表——本次改动动了什么，决定给哪套命令：

| 改动范围 | 需要的动作 |
|---|---|
| 仅前端 | 只传 frontend-dist.tar.gz + 前端软链切换 |
| 动了后端代码 | 两个包都传 + 后端解包 + `systemctl restart career-rag` |
| 新增 Python 依赖 | 额外 `pip install -r app/requirements.txt` |
| 新增数据库迁移 | 额外 `python -m app.db.migrate`，并用 `schema_migrations` 表查询确认（migrate 永远静默，不能以无输出判断成败） |
| 改了 Caddyfile | 额外 `caddy validate` + `systemctl reload caddy` |

标准全量模板（用户粘贴用；只前端时删去后端段）：

```bash
# 用户本机（项目根目录）：
scp app.tar.gz frontend-dist.tar.gz root@45.153.131.127:/opt/career-rag/

# 用户 SSH 进服务器后（顺序写死：后端先行，前端后切）：
cd /opt/career-rag && tar -xzf app.tar.gz -C app && chown -R career:career app \
  && systemctl restart career-rag && sleep 8 \
  && curl -s http://127.0.0.1:8000/api/v1/capabilities \
  && REL=/opt/career-rag/releases/frontend-$(date +%Y%m%d%H%M) && mkdir -p "$REL" \
  && tar -xzf /opt/career-rag/frontend-dist.tar.gz -C "$REL" \
  && ln -sfn "$REL" /opt/career-rag/current.tmp \
  && mv -Tf /opt/career-rag/current.tmp /opt/career-rag/frontend-current \
  && echo "DONE $(readlink /opt/career-rag/frontend-current)"
```

成功判据：中途 `curl` 吐出 capabilities JSON（后端活了），
末尾回显 `DONE /opt/career-rag/releases/frontend-<时间戳>`（软链切换
完成）。「后端先行、前端后切」不可颠倒：新前端撞旧后端可能绕过
确认制闸门（见 deploy_guide）。

## 6. 部署后：你怎么验证（无凭据、公网只读）

```powershell
# 后端健康 + 能力旗
curl -s https://zhangen.cn/api/v1/capabilities
# 前端确已切到新包：线上引用的 bundle 名必须等于本机 dist 里的名字
curl -s https://zhangen.cn | Select-String -Pattern 'index-[A-Za-z0-9_-]+\.js'
Get-ChildItem frontend\dist\assets\*.js
```

两个名字一致即部署成功，可据此向用户报「上线完成」。

## 7. 回滚

- 前端：把软链指回上一个 releases 目录即可
  （`ln -sfn /opt/career-rag/releases/frontend-<旧时间戳> ...` 同样的
  tmp+mv 原子写法）。
- 后端：重新解包上一个 app.tar.gz（用户档案里有），或 git archive
  旧提交现打；功能层面优先用 `.env` 开关关闭再重启。
- 数据库迁移不自动回滚，设计上迁移全部向前兼容。

## 8. 常见误解对照

| 误解 | 事实 |
|---|---|
| 「push 到 GitHub 就算部署了」 | 不算，服务器不拉仓库，必须走 §4-§5 |
| 「AI 直接 ssh 上去改」 | 禁止，凭据在用户手里 |
| 「migrate 没输出＝失败」 | migrate 永远静默，以 schema_migrations 查询为准 |
| 「先切前端再重启后端」 | 顺序写死后端先行，颠倒会绕过成本闸 |
| 「部署包要提交进 git」 | 不入库，用完即弃，随时可重建 |
