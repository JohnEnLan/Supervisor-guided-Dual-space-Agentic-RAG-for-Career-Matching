from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.matching_agent import enrich_top_match_explanations
from app.retrieval.hybrid_search import JobCandidate
from app.state.schema import ResumeState, SharedState, StrategyState


async def run_benchmark(
    *,
    candidates: int = 5,
    simulated_latency_ms: int = 300,
    semaphore_limit: int = 5,
) -> list[dict[str, int | float | str]]:
    benchmark_candidates = _build_candidates(candidates)
    serial = await _measure_mode(
        "serial",
        benchmark_candidates,
        simulated_latency_ms=simulated_latency_ms,
        semaphore_limit=semaphore_limit,
    )
    parallel = await _measure_mode(
        "parallel",
        benchmark_candidates,
        simulated_latency_ms=simulated_latency_ms,
        semaphore_limit=semaphore_limit,
    )
    return [serial, parallel]


def format_benchmark_markdown(rows: list[dict[str, int | float | str]]) -> str:
    headers = ["mode", "candidates", "semaphore_limit", "elapsed_ms", "max_active_calls"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _header in headers) + " |",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join(str(row[header]) for header in headers) + " |"
        )
    return "\n".join(lines)


async def _measure_mode(
    mode: str,
    candidates: list[JobCandidate],
    *,
    simulated_latency_ms: int,
    semaphore_limit: int,
) -> dict[str, int | float | str]:
    state = _build_state(candidates)
    stats = {"active": 0, "max_active": 0}
    semaphore = asyncio.Semaphore(semaphore_limit)
    chat_fn = _fake_chat_fn(
        simulated_latency_ms=simulated_latency_ms,
        semaphore=semaphore,
        stats=stats,
    )

    started = time.perf_counter()
    if mode == "serial":
        for candidate in candidates[:5]:
            await enrich_top_match_explanations(
                state,
                [candidate],
                top_n=1,
                chat_fn=chat_fn,
            )
    elif mode == "parallel":
        await enrich_top_match_explanations(
            state,
            candidates,
            top_n=5,
            chat_fn=chat_fn,
        )
    else:
        raise ValueError(f"unknown benchmark mode: {mode}")

    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "mode": mode,
        "candidates": min(len(candidates), 5),
        "semaphore_limit": semaphore_limit,
        "elapsed_ms": round(elapsed_ms, 2),
        "max_active_calls": int(stats["max_active"]),
    }


def _fake_chat_fn(
    *,
    simulated_latency_ms: int,
    semaphore: asyncio.Semaphore,
    stats: dict[str, int],
):
    async def fake_chat(system: str, user: str, **kwargs: Any) -> str:
        payload = json.loads(user)
        candidate = payload["candidate"]
        async with semaphore:
            stats["active"] += 1
            stats["max_active"] = max(stats["max_active"], stats["active"])
            try:
                await asyncio.sleep(simulated_latency_ms / 1000)
            finally:
                stats["active"] -= 1
        return json.dumps(
            {
                "recommended_roles": [
                    {
                        "job_id": candidate["job_id"],
                        "tier": "now_fit",
                        "match_explanation": (
                            f"Simulated evidence-backed explanation for "
                            f"{candidate['job_id']}."
                        ),
                        "evidence_span_ids": candidate["evidence_span_ids"],
                    }
                ]
            }
        )

    return fake_chat


def _build_candidates(count: int) -> list[JobCandidate]:
    return [
        JobCandidate(
            job_id=f"job-{index + 1}",
            score=1.0 - index * 0.01,
            title=f"Candidate Role {index + 1}",
            evidence_span_ids=[f"job-{index + 1}:skills:1"],
            evidence_spans=[
                {
                    "evidence_span_id": f"job-{index + 1}:skills:1",
                    "field": "required_skills",
                    "content": "Python, SQL, and communication evidence.",
                }
            ],
        )
        for index in range(count)
    ]


def _build_state(candidates: list[JobCandidate]) -> SharedState:
    return SharedState(
        session_id="benchmark",
        user_id="benchmark-user",
        resume_state=ResumeState(
            normalized_base_resume="Python SQL analyst resume",
            skills=["Python", "SQL"],
        ),
        strategy_state=StrategyState(
            recommended_roles=[
                {
                    "job_id": candidate.job_id,
                    "tier": "stretch_fit",
                    "match_explanation": "",
                    "evidence_span_ids": list(candidate.evidence_span_ids),
                }
                for candidate in candidates
            ]
        ),
    )


async def _main_async(args: argparse.Namespace) -> None:
    rows = await run_benchmark(
        candidates=args.candidates,
        simulated_latency_ms=args.simulated_latency_ms,
        semaphore_limit=args.semaphore_limit,
    )
    if args.format == "json":
        print(json.dumps(rows, indent=2))
    else:
        print(format_benchmark_markdown(rows))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark serial vs parallel Top-5 matching explanation calls "
            "with simulated LLM latency."
        )
    )
    parser.add_argument("--candidates", type=int, default=5)
    parser.add_argument("--simulated-latency-ms", type=int, default=300)
    parser.add_argument("--semaphore-limit", type=int, default=5)
    parser.add_argument("--format", choices=["table", "json"], default="table")
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
