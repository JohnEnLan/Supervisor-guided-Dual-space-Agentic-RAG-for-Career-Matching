# 部署指南：zhangen.cn @ 45.153.131.127（香港 · Ubuntu 22.04）

> 所有「本机」命令在你 Windows 的 PowerShell 里跑；所有「服务器」命令是
> `ssh root@45.153.131.127` 登进去之后贴。配套文件在 `deploy/`。
> 上传包由 Claude 预先在本机生成（第 2 步）。

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

登进去后，先把 `deploy/server_setup.sh` 内容上传（第 2 步的包里有），或直接：

```bash
mkdir -p /opt/career-rag
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
mkdir -p app frontend-dist
tar -xzf app.tar.gz -C app
tar -xzf frontend-dist.tar.gz -C frontend-dist
cp env.production.template app/.env
nano app/.env    # 按模板注释逐项填：DB 密码、各 API key、新 JWT 秘钥、QQ 授权码
```

Python 环境：

```bash
python3.11 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r app/requirements.txt
chown -R career:career /opt/career-rag
```

## 第 5 步（服务器）：导入数据 + 迁移

```bash
sudo -u postgres pg_restore -d career_rag --no-owner --role=career -j 2 /opt/career-rag/career_rag.dump
sudo -u postgres psql -d career_rag -c "REASSIGN OWNED BY postgres TO career;" || true
cd /opt/career-rag/app && sudo -u career ../venv/bin/python -m app.db.migrate
```

（restore 含 HNSW 索引重建，2 核机器上可能要几分钟，正常。）

## 第 6 步（服务器）：服务上线

```bash
cp /opt/career-rag/career-rag.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now career-rag
systemctl status career-rag --no-pager    # 应显示 active (running)

cp /opt/career-rag/Caddyfile /etc/caddy/Caddyfile
systemctl reload caddy
```

Caddy 会在域名解析生效后**自动申请 HTTPS 证书**（首次访问约几秒）。

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
