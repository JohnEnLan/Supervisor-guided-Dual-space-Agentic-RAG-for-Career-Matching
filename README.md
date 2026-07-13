# Supervisor-guided Dual-space Agentic RAG for Career Matching

This repository contains a dissertation project for building a
Supervisor-guided dual-space Agentic RAG system for career matching.

The system upgrades a traditional resume-job semantic matching RAG pipeline
into a supervised multi-agent workflow. It uses hybrid retrieval to find
evidence-grounded job candidates, then uses LLM-based agents to reason about
user intent, job fit, resume strategy, and career development.

## Project Focus

The one-month implementation target is to make the main P0 workflow run end to
end:

```text
data ingestion
  -> resume normalization
  -> hybrid retrieval
  -> Top-K job matching
  -> three business agents + supervisor
  -> FastAPI multi-user service
  -> evaluation metrics
```

P1 features, such as dual-space memory, feedback loops, and anonymized case
base examples, are used as mechanism demonstrations. P2 features, such as
RAPTOR and cross-encoder reranking, are intentionally kept out of the main
workflow unless time allows.

## Architecture

The core design is:

- RAG core: metadata filtering, BM25, dense retrieval, RRF fusion, and
  bi-encoder scoring.
- Agent workflow: Intent Agent, Matching Agent, and Strategy Agent share one
  structured state object.
- Supervisor: bounded verification and repair loops for clarification,
  re-retrieval, and final quality checks.
- Stateless service: all shared state is stored by `session_id` in PostgreSQL.
- Async execution: FastAPI, asyncpg connection pooling, and semaphore-limited
  LLM / embedding calls.

## Repository Layout

```text
app/
  agents/          LLM agent harness and business agents
  api/             FastAPI entrypoint and routes
  db/              asyncpg pool, PostgreSQL schema, state store
  evaluation/      ranking metrics
  llm/             DeepSeek and Qwen embedding clients
  memory/          private memory, feedback, anonymized case base
  normalization/   resume intake and evidence-preserving normalization
  retrieval/       hybrid search, RRF, RAPTOR placeholder
  state/           shared structured state schema
scripts/           data loading and sample case scripts
data/              local job, resume, and case data placeholders
tests/             regression tests for retrieval, agents, API, memory, evaluation
frontend/          React/Vite 答辩工作台、进度板、证据和监控页面
```

## Setup

Copy the environment template and fill in local secrets:

```bash
cp .env.example .env
```

Install dependencies:

```bash
pip install -r requirements.txt
```

The project expects:

- Python 3.11+
- PostgreSQL with pgvector
- DeepSeek API credentials
- Qwen / DashScope embedding credentials

Real credentials must stay in `.env`; `.env` is ignored by Git.

## Current Status

The P0 path now has tested modules for resume intake, hybrid retrieval, the
three-agent workflow, Supervisor verification, persisted orchestration, and
FastAPI polling routes. State is stored by `session_id` in PostgreSQL.

Start the API locally:

```bash
uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

Minimal API flow:

```bash
curl -X POST http://127.0.0.1:8000/resume \
  -F "session_id=s1" \
  -F "user_id=u1" \
  -F "file=@data/resumes/sample.txt"

curl -X POST http://127.0.0.1:8000/match \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s1","user_goal_text":"Find data analyst jobs in Birmingham","top_k":5}'

curl http://127.0.0.1:8000/status/s1
```

## React 答辩工作台

先应用数据库 migration，并启动 v1 API：

```powershell
.\.venv\Scripts\python.exe -m app.db.migrate
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

另开一个终端启动前端：

```powershell
cd frontend
npm.cmd install
npm.cmd run dev
```

浏览器打开 `http://127.0.0.1:5173`。工作台主流程为：

```text
上传简历 → 确认结构化事实 → 目标咨询 Agent
→ 批准 Match Brief → 查看 7 阶段进度 → 推荐/证据 → 评估解释/反馈
```

页面不展示录用概率、完整归一化简历、内部 state、提示词或供应商错误。

## 只读运行监控

在 `.env` 中开启：

```dotenv
MONITORING_ENABLED=true
```

重启 API 后访问 `http://127.0.0.1:5173/monitoring`。监控页面每 5 秒读取一次持久化的 allow-list 指标，包括运行量、完成/失败/警告率、P50/P95 耗时、推荐数量、JD 证据覆盖率、隐式空间使用率、重排次数和最近运行。该页面没有删除或修改接口，也不包含用户身份与简历正文。

## 前端验收

```powershell
cd frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd run e2e
```

Playwright 覆盖完整产品流程、证据抽屉焦点恢复、Examiner View、反馈、监控页面以及 375/768/1440 像素宽度下的横向溢出检查。
