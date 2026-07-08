"""Build a reproducible LinkedIn job-posting sample from the Kaggle export."""
from __future__ import annotations

import argparse
import csv
import heapq
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DATASET_SLUG = "arshkon/linkedin-job-postings"
RELATED_FILES = {
    "linkedin_job_skills": Path("jobs/job_skills.csv"),
    "linkedin_job_industries": Path("jobs/job_industries.csv"),
    "linkedin_salaries": Path("jobs/salaries.csv"),
    "linkedin_benefits": Path("jobs/benefits.csv"),
}


@dataclass(frozen=True)
class SampleSummary:
    limit: int
    source_root: Path
    output_dir: Path
    posting_count: int
    related_counts: dict[str, int]
    selected_job_ids: list[str]


def _nonempty(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _job_id_key(row: dict[str, str]) -> int | None:
    job_id = _nonempty(row.get("job_id"))
    if job_id is None:
        return None
    try:
        return int(job_id)
    except ValueError:
        return None


def _is_loadable_posting(row: dict[str, str]) -> bool:
    return (
        _job_id_key(row) is not None
        and _nonempty(row.get("title")) is not None
        and _nonempty(row.get("description")) is not None
    )


def _select_first_loadable_postings(
    postings_path: Path, *, limit: int
) -> tuple[list[str], list[dict[str, str]]]:
    if limit <= 0:
        raise ValueError("limit must be positive")

    heap: list[tuple[int, int, dict[str, str]]] = []
    with postings_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for counter, row in enumerate(reader):
            if not _is_loadable_posting(row):
                continue
            sort_key = _job_id_key(row)
            if sort_key is None:
                continue
            heapq.heappush(heap, (-sort_key, counter, row))
            if len(heap) > limit:
                heapq.heappop(heap)

    if len(heap) < limit:
        raise ValueError(
            f"Only found {len(heap)} loadable postings in {postings_path}; need {limit}."
        )

    rows = [entry[2] for entry in heap]
    rows.sort(key=lambda row: _job_id_key(row) or 0)
    return fieldnames, rows


def _write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, str]]) -> int:
    names = list(fieldnames)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def _filter_related_file(
    source_path: Path, output_path: Path, selected_job_ids: set[str]
) -> int:
    if not source_path.exists():
        raise FileNotFoundError(source_path)

    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = [
            row
            for row in reader
            if (_nonempty(row.get("job_id")) or "") in selected_job_ids
        ]
    return _write_csv(output_path, fieldnames, rows)


def _write_manifest(summary: SampleSummary) -> Path:
    manifest_path = summary.output_dir / f"linkedin_{summary.limit}_manifest.txt"
    related_files = ", ".join(
        f"{name}_{summary.limit}.csv" for name in RELATED_FILES
    )
    lines = [
        f"Source: Kaggle dataset {DATASET_SLUG}",
        f"Full dataset location: {summary.source_root.resolve()}",
        (
            "Sample rule: first "
            f"{summary.limit} postings sorted by numeric job_id with non-empty title and description"
        ),
        f"Main file: linkedin_postings_{summary.limit}.csv",
        f"Related files: {related_files}",
        f"Posting rows: {summary.posting_count}",
        "Related row counts:",
    ]
    for name, count in summary.related_counts.items():
        lines.append(f"- {name}_{summary.limit}.csv: {count}")
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path


def build_linkedin_sample(
    *, source_root: Path, output_dir: Path, limit: int = 1000
) -> SampleSummary:
    postings_path = source_root / "postings.csv"
    if not postings_path.exists():
        raise FileNotFoundError(postings_path)

    fieldnames, posting_rows = _select_first_loadable_postings(postings_path, limit=limit)
    selected_job_ids = [row["job_id"] for row in posting_rows]
    selected_job_id_set = set(selected_job_ids)

    posting_count = _write_csv(
        output_dir / f"linkedin_postings_{limit}.csv",
        fieldnames,
        posting_rows,
    )

    related_counts: dict[str, int] = {}
    for output_stem, relative_source in RELATED_FILES.items():
        related_counts[output_stem] = _filter_related_file(
            source_root / relative_source,
            output_dir / f"{output_stem}_{limit}.csv",
            selected_job_id_set,
        )

    summary = SampleSummary(
        limit=limit,
        source_root=source_root,
        output_dir=output_dir,
        posting_count=posting_count,
        related_counts=related_counts,
        selected_job_ids=selected_job_ids,
    )
    _write_manifest(summary)
    return summary


def _summary_to_json(summary: SampleSummary) -> str:
    return json.dumps(
        {
            "limit": summary.limit,
            "source_root": str(summary.source_root),
            "output_dir": str(summary.output_dir),
            "posting_count": summary.posting_count,
            "related_counts": summary.related_counts,
            "first_job_id": summary.selected_job_ids[0] if summary.selected_job_ids else None,
            "last_job_id": summary.selected_job_ids[-1] if summary.selected_job_ids else None,
        },
        ensure_ascii=False,
        indent=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a fixed-size sample from the LinkedIn Kaggle dataset."
    )
    parser.add_argument(
        "--source-root",
        default="../dataset",
        type=Path,
        help="Directory containing postings.csv and jobs/*.csv from Kaggle.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/jobs",
        type=Path,
        help="Directory where sampled CSV files should be written.",
    )
    parser.add_argument("--limit", default=1000, type=int)
    args = parser.parse_args()

    summary = build_linkedin_sample(
        source_root=args.source_root,
        output_dir=args.output_dir,
        limit=args.limit,
    )
    print(_summary_to_json(summary))


if __name__ == "__main__":
    main()
