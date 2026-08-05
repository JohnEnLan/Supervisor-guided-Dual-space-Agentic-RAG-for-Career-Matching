from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.transform_jobs_cn_uk import (
    ACCEPTED_ROW_COUNT,
    CN_COMPANIES,
    CN_COUNTRY_QUOTA,
    CN_LOCATIONS,
    DATASET_ID,
    UK_COMPANIES,
    UK_COUNTRY_QUOTA,
    UK_LOCATIONS,
    assign_country_codes,
    is_visa_sponsor,
    read_accepted_rows,
    transform_corpus,
)


SOURCE_FIELDS = [
    "Co_Nm",
    "Co_Pg_Lstd",
    "Emp_Cnt",
    "Flw_Cnt",
    "Job_Ttl",
    "Job_Desc",
    "Is_Supvsr",
    "max_sal",
    "med_sal",
    "min_sal",
    "py_prd",
    "py_lstd",
    "wrk_typ",
    "loc",
    "st_code",
    "is_remote",
    "views",
    "app_typ",
    "app_is_off",
    "xp_lvl",
    "domain",
    "has_post_domain",
    "is_sponsored",
    "base_comp",
]


def _row(
    number: int,
    *,
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    description: str | None = None,
) -> dict[str, str]:
    row = {field: "" for field in SOURCE_FIELDS}
    row.update(
        {
            "Co_Nm": company or f"Source Company {number}",
            "Job_Ttl": title or f"Data Role {number}",
            "Job_Desc": description or (f"Evidence {number}. " + "x" * 340),
            "loc": location or f"Source City {number}",
            "max_sal": str(100_000 + number),
            "med_sal": str(90_000 + number),
            "min_sal": str(80_000 + number),
            "py_prd": "YEARLY",
            "domain": "example.org",
        }
    )
    return row


def _write_source(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_acceptance_rules_keep_first_unique_source_record(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    valid = _row(1)
    duplicate = dict(valid)
    duplicate["views"] = "999"
    _write_source(
        source,
        [
            valid,
            duplicate,
            _row(2, company="No Company Page"),
            _row(3, company="Company Page"),
            _row(4, description="z" * 300),
            _row(5, description="z" * 301),
        ],
    )

    accepted, rejection_counts = read_accepted_rows(source, expected_count=2)

    assert [item.source_row_number for item in accepted] == [1, 6]
    assert rejection_counts == {
        "duplicate_canonical_job": 1,
        "sentinel_company": 2,
        "jd_not_over_300_chars": 1,
    }
    assert accepted[0].source_metadata["max_sal"] == valid["max_sal"]
    assert accepted[0].source_metadata["py_prd"] == "YEARLY"


def test_country_assignment_uses_exact_reproducible_quota() -> None:
    hashes = [hashlib.sha256(f"row-{index}".encode()).hexdigest() for index in range(ACCEPTED_ROW_COUNT)]

    first = assign_country_codes(hashes, cn_quota=CN_COUNTRY_QUOTA)
    second = assign_country_codes(list(reversed(hashes)), cn_quota=CN_COUNTRY_QUOTA)

    assert first == second
    assert sum(country == "CN" for country in first.values()) == CN_COUNTRY_QUOTA
    assert sum(country == "UK" for country in first.values()) == UK_COUNTRY_QUOTA


def test_visa_distribution_stays_within_country_tolerance() -> None:
    hashes = [hashlib.sha256(f"visa-{index}".encode()).hexdigest() for index in range(20_000)]
    cn_ratio = sum(is_visa_sponsor(value, "CN") for value in hashes) / len(hashes)
    uk_ratio = sum(is_visa_sponsor(value, "UK") for value in hashes) / len(hashes)

    assert cn_ratio == pytest.approx(0.05, abs=0.01)
    assert uk_ratio == pytest.approx(0.35, abs=0.02)


def test_transform_is_byte_deterministic_and_emits_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    rows = [_row(index, title="Shared title") for index in range(1, 5)]
    _write_source(source, rows)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    first = transform_corpus(
        source,
        first_dir / "cnuk_demo_v1.csv",
        first_dir / "manifest.json",
        expected_count=4,
        cn_quota=3,
    )
    second = transform_corpus(
        source,
        second_dir / "cnuk_demo_v1.csv",
        second_dir / "manifest.json",
        expected_count=4,
        cn_quota=3,
    )

    assert (first_dir / "cnuk_demo_v1.csv").read_bytes() == (
        second_dir / "cnuk_demo_v1.csv"
    ).read_bytes()
    assert (first_dir / "manifest.json").read_bytes() == (
        second_dir / "manifest.json"
    ).read_bytes()
    assert first == second
    assert first["dataset_id"] == DATASET_ID
    assert first["row_count"] == 4
    assert first["country_counts"] == {"CN": 3, "UK": 1}
    assert first["embedding_fingerprint"] == {
        "model": None,
        "dimension": None,
        "splitter_version": None,
        "build_id": None,
    }
    assert first["output_file"]["sha256"] == hashlib.sha256(
        (first_dir / "cnuk_demo_v1.csv").read_bytes()
    ).hexdigest()

    with (first_dir / "cnuk_demo_v1.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        converted = list(csv.DictReader(handle))
    assert all(row["demo_synthetic"] == "true" for row in converted)
    assert all(row["source_tag"] == DATASET_ID for row in converted)
    assert all(row["country_code"] in {"CN", "UK"} for row in converted)
    assert all(
        row["company"] in (CN_COMPANIES if row["country_code"] == "CN" else UK_COMPANIES)
        for row in converted
    )
    assert all(
        row["location"] in (CN_LOCATIONS if row["country_code"] == "CN" else UK_LOCATIONS)
        for row in converted
    )
    assert all(row["raw_jd"].splitlines()[0].startswith("演示背景：") for row in converted)
    assert all(row["salary_min"] == row["salary_max"] == "" for row in converted)
    metadata = json.loads(converted[0]["source_metadata"])
    assert metadata["max_sal"]
    assert metadata["med_sal"]
    assert metadata["min_sal"]
    assert metadata["py_prd"] == "YEARLY"
    assert metadata["visa_sponsor_provenance"] == "synthetic_scenario"
    assert first["collisions"]["colliding_row_count"] >= 0


@pytest.mark.parametrize(
    "script_name",
    [
        "transform_jobs_cn_uk.py",
        "import_cnuk_demo.py",
        "cutover_cnuk_demo.py",
        "rollback_cnuk_demo.py",
    ],
)
def test_w5_scripts_support_direct_cli_execution_from_any_cwd(
    tmp_path: Path,
    script_name: str,
) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / script_name

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
