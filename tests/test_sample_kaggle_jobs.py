import csv
from pathlib import Path

import pytest


def _write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_build_linkedin_sample_selects_sorted_loadable_jobs_and_related_rows(tmp_path):
    from scripts.sample_kaggle_jobs import build_linkedin_sample

    source_root = tmp_path / "dataset"
    output_dir = tmp_path / "out"
    posting_fields = ["job_id", "title", "description", "company_name"]
    _write_rows(
        source_root / "postings.csv",
        posting_fields,
        [
            {
                "job_id": "10",
                "title": "Later Job",
                "description": "valid",
                "company_name": "Example",
            },
            {
                "job_id": "2",
                "title": "Second Job",
                "description": "valid",
                "company_name": "Example",
            },
            {
                "job_id": "1",
                "title": "First Job",
                "description": "",
                "company_name": "Example",
            },
            {
                "job_id": "5",
                "title": "Fifth Job",
                "description": "valid",
                "company_name": "Example",
            },
            {
                "job_id": "3",
                "title": "Third Job",
                "description": "valid",
                "company_name": "Example",
            },
        ],
    )
    related_fields = ["job_id", "value"]
    for relative_path in [
        "jobs/job_skills.csv",
        "jobs/job_industries.csv",
        "jobs/salaries.csv",
        "jobs/benefits.csv",
    ]:
        _write_rows(
            source_root / relative_path,
            related_fields,
            [
                {"job_id": "2", "value": "keep"},
                {"job_id": "3", "value": "keep"},
                {"job_id": "10", "value": "drop"},
                {"job_id": "999", "value": "drop"},
            ],
        )

    summary = build_linkedin_sample(
        source_root=source_root,
        output_dir=output_dir,
        limit=3,
    )

    postings = _read_rows(output_dir / "linkedin_postings_3.csv")
    assert [row["job_id"] for row in postings] == ["2", "3", "5"]
    assert summary.posting_count == 3
    assert summary.selected_job_ids == ["2", "3", "5"]

    skills = _read_rows(output_dir / "linkedin_job_skills_3.csv")
    assert [row["job_id"] for row in skills] == ["2", "3"]
    assert summary.related_counts["linkedin_job_skills"] == 2

    manifest = (output_dir / "linkedin_3_manifest.txt").read_text(encoding="utf-8")
    assert "arshkon/linkedin-job-postings" in manifest
    assert "Posting rows: 3" in manifest


def test_build_linkedin_sample_requires_enough_loadable_postings(tmp_path):
    from scripts.sample_kaggle_jobs import build_linkedin_sample

    source_root = tmp_path / "dataset"
    _write_rows(
        source_root / "postings.csv",
        ["job_id", "title", "description"],
        [{"job_id": "1", "title": "Only Job", "description": "valid"}],
    )
    for relative_path in [
        "jobs/job_skills.csv",
        "jobs/job_industries.csv",
        "jobs/salaries.csv",
        "jobs/benefits.csv",
    ]:
        _write_rows(source_root / relative_path, ["job_id", "value"], [])

    with pytest.raises(ValueError, match="Only found 1 loadable postings"):
        build_linkedin_sample(
            source_root=source_root,
            output_dir=tmp_path / "out",
            limit=2,
        )


def test_generated_linkedin_1000_sample_has_expected_counts_and_relationships():
    base = Path("data/jobs")
    postings = _read_rows(base / "linkedin_postings_1000.csv")
    posting_ids = {row["job_id"] for row in postings}

    assert len(postings) == 1000
    assert len(posting_ids) == 1000
    assert all(row["title"].strip() for row in postings)
    assert all(row["description"].strip() for row in postings)

    for name in [
        "linkedin_job_skills_1000.csv",
        "linkedin_job_industries_1000.csv",
        "linkedin_salaries_1000.csv",
        "linkedin_benefits_1000.csv",
    ]:
        rows = _read_rows(base / name)
        assert {row["job_id"] for row in rows} <= posting_ids

    manifest = (base / "linkedin_1000_manifest.txt").read_text(encoding="utf-8")
    assert "Posting rows: 1000" in manifest
