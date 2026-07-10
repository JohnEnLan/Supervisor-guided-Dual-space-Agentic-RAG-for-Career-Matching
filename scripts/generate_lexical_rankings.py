from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


METHOD = "deterministic_weighted_token_overlap_v1"
RUN_NAME = "offline_lexical_baseline"
TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:[.+#-][a-z0-9]+)*")


def generate_lexical_ranking_artifact(
    *, corpus_path: Path, queries_path: Path, top_k: int
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    job_rows = _read_csv(corpus_path)
    queries = _read_jsonl(queries_path)
    job_ids = [str(row.get("job_id") or "").strip() for row in job_rows]
    if not all(job_ids) or len(job_ids) != len(set(job_ids)):
        raise ValueError("corpus job_id values must be non-empty and unique")

    documents = [_weighted_document_tokens(row) for row in job_rows]
    document_frequency = Counter(
        token for document in documents for token in document
    )
    corpus_size = len(documents)
    idf = {
        token: math.log((corpus_size + 1) / (frequency + 1)) + 1.0
        for token, frequency in document_frequency.items()
    }

    rankings: dict[str, list[str]] = {}
    for query in queries:
        case_id = str(query.get("case_id") or "").strip()
        query_text = str(query.get("query") or "").strip()
        if not case_id or not query_text:
            raise ValueError("each query requires non-empty case_id and query")
        query_tokens = Counter(_tokenize(query_text))
        scored = [
            (
                _score_document(query_tokens, document, idf),
                job_id,
            )
            for job_id, document in zip(job_ids, documents, strict=True)
        ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        rankings[case_id] = [job_id for _score, job_id in scored[:top_k]]

    return {
        "metadata": {
            "artifact_kind": "offline_lexical_baseline",
            "label": "Offline lexical baseline (not live hybrid-system performance)",
            "corpus_path": corpus_path.as_posix(),
            "corpus_sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
            "corpus_row_count": len(job_rows),
            "query_path": queries_path.as_posix(),
            "query_count": len(queries),
            "method": METHOD,
            "top_k": top_k,
        },
        "rankings": {RUN_NAME: rankings},
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _weighted_document_tokens(row: dict[str, str]) -> Counter[str]:
    tokens: Counter[str] = Counter()
    title_tokens = Counter(_tokenize(row.get("title", "")))
    skill_tokens = Counter(_tokenize(row.get("skills_desc", "")))
    tokens.update({token: count * 3 for token, count in title_tokens.items()})
    tokens.update({token: count * 2 for token, count in skill_tokens.items()})
    tokens.update(_tokenize(row.get("description", "")))
    return tokens


def _tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(str(text).casefold())


def _score_document(
    query: Counter[str], document: Counter[str], idf: dict[str, float]
) -> float:
    return sum(
        query_count * min(document.get(token, 0), 5) * idf.get(token, 0.0)
        for token, query_count in query.items()
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic offline lexical ranking baseline."
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("data/jobs/linkedin_postings_1000.csv"),
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=Path("data/eval/resume_queries.jsonl"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/eval/offline_lexical_rankings_1000.json"),
    )
    parser.add_argument("--top-k", type=int, default=20)
    args = parser.parse_args()

    artifact = generate_lexical_ranking_artifact(
        corpus_path=args.corpus,
        queries_path=args.queries,
        top_k=args.top_k,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(artifact["metadata"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
