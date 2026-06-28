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
tests/             test suite placeholder
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

This is an early scaffold. The priority is to implement one module at a time
and keep the P0 path runnable before adding optional research extensions.
