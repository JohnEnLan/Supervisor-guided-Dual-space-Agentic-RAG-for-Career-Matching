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

migrate **静默退出即成功**（快照自带全部迁移记录，无迁移可补时不打印任何东西）。
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
# ① 后端：解包 → 迁移 → 重启 → 健康检查
cd /opt/career-rag && tar -xzf app.tar.gz -C app && chown -R career:career app
cd /opt/career-rag/app && sudo -u career ../venv/bin/python -m app.db.migrate
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
