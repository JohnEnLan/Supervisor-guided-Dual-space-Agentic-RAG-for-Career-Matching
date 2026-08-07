#!/usr/bin/env bash
# Career-RAG 服务器一键初始化（Ubuntu 22.04，root 执行）
# 用法：bash server_setup.sh
set -euo pipefail

echo "=== [1/7] 系统更新与基础工具 ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y curl gnupg lsb-release ufw unzip

echo "=== [2/7] 2G swap（防内存尖峰 OOM）==="
if ! swapon --show | grep -q swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "=== [3/7] PostgreSQL 17 + pgvector ==="
install -d /usr/share/postgresql-common/pgdg
curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
  -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc
echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] \
http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
  > /etc/apt/sources.list.d/pgdg.list
apt-get update -y
apt-get install -y postgresql-17 postgresql-17-pgvector
systemctl enable --now postgresql

# 4G 内存调参
PGCONF=/etc/postgresql/17/main/postgresql.conf
sed -i "s/^#\?shared_buffers.*/shared_buffers = 1GB/" "$PGCONF"
sed -i "s/^#\?effective_cache_size.*/effective_cache_size = 2GB/" "$PGCONF"
sed -i "s/^#\?work_mem.*/work_mem = 16MB/" "$PGCONF"
sed -i "s/^#\?maintenance_work_mem.*/maintenance_work_mem = 128MB/" "$PGCONF"
systemctl restart postgresql

echo "=== [4/7] 数据库与用户（密码首次运行时生成并打印，请记录）==="
DB_PASS=$(openssl rand -hex 16)
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'career') THEN
    CREATE ROLE career LOGIN PASSWORD '${DB_PASS}';
  END IF;
END \$\$;
SELECT 'CREATE DATABASE career_rag OWNER career'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'career_rag') \gexec
SQL
sudo -u postgres psql -d career_rag -c "CREATE EXTENSION IF NOT EXISTS vector;"
sudo -u postgres psql -d career_rag -c "ALTER SCHEMA public OWNER TO career; GRANT ALL ON SCHEMA public TO career;"
echo ">>> 数据库密码（写进 .env 的 DATABASE_URL）： ${DB_PASS}"

echo "=== [5/7] Python 3.11 ==="
apt-get install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -y
apt-get install -y python3.11 python3.11-venv python3.11-dev

echo "=== [6/7] Caddy（自动 HTTPS 反代）==="
apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  > /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y && apt-get install -y caddy

echo "=== [7/7] 防火墙 ==="
ufw allow OpenSSH && ufw allow 80 && ufw allow 443
ufw --force enable

echo ""
echo "=== 初始化完成 ==="
echo "下一步：解包应用（见 deploy_guide.md 第 4 步）"
