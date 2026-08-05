"""Deterministically transform the local LinkedIn ML corpus for CN/UK demos."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.load_jobs import _build_chunk_specs


DATASET_ID = "linkedin_ml_cnuk_demo_v1"
ACCEPTED_ROW_COUNT = 31_879
CN_COUNTRY_QUOTA = 22_315
UK_COUNTRY_QUOTA = 9_564
CANONICALIZATION_VERSION = "linkedin_ml_canonical_v1"
TRANSFORM_VERSION = "cnuk_demo_transform_v1"

CN_COMPANIES = (
    "腾讯",
    "阿里巴巴",
    "字节跳动",
    "华为",
    "美团",
    "京东",
    "网易",
    "百度",
    "小米",
    "比亚迪",
    "蔚来",
    "理想",
    "大疆",
    "小红书",
    "携程",
    "拼多多",
    "米哈游",
    "科大讯飞",
    "商汤",
    "旷视",
    "海康威视",
    "宁德时代",
    "顺丰",
    "招商银行",
    "平安科技",
    "蚂蚁集团",
    "快手",
    "B站",
    "知乎",
    "贝壳",
    "金山",
    "用友",
    "金蝶",
    "恒瑞医药",
    "药明康德",
    "迈瑞医疗",
    "联影",
    "汇川技术",
    "中兴",
    "OPPO",
    "vivo",
    "荣耀",
    "TCL",
    "海尔",
    "格力",
    "安克",
    "影石",
    "石头科技",
    "涂鸦智能",
    "地平线",
    "黑芝麻",
    "亿纬锂能",
    "隆基绿能",
    "通威",
    "三一重工",
    "中联重科",
    "京东方",
    "立讯精密",
    "蓝思科技",
    "歌尔",
)
UK_COMPANIES = (
    "HSBC",
    "Barclays",
    "Lloyds",
    "NatWest",
    "Revolut",
    "Monzo",
    "Wise",
    "Starling",
    "DeepMind",
    "Arm",
    "Graphcore",
    "Darktrace",
    "AstraZeneca",
    "GSK",
    "BP",
    "Shell UK",
    "Rolls-Royce",
    "BAE Systems",
    "Sky",
    "BBC",
    "Ocado",
    "Tesco",
    "Sainsbury",
    "Dyson",
    "JLR",
    "Vodafone",
    "BT",
    "Deliveroo",
    "Checkout.com",
    "Sage",
)
CN_LOCATIONS = ("北京", "上海", "深圳", "杭州", "广州", "成都", "南京", "苏州", "武汉", "西安")
UK_LOCATIONS = ("London", "Manchester", "Cambridge", "Edinburgh", "Bristol", "Leeds", "Birmingham")

OUTPUT_FIELDS = (
    "job_id",
    "source_record_hash",
    "posting_group_hash",
    "title",
    "company",
    "location",
    "country_code",
    "visa_sponsor",
    "demo_synthetic",
    "source_tag",
    "role_cluster",
    "is_open",
    "degree_required",
    "min_years_exp",
    "responsibilities",
    "required_skills",
    "nice_to_have",
    "deadline",
    "salary_min",
    "salary_max",
    "raw_jd",
    "source_metadata",
)

_WHITESPACE = re.compile(r"\s+", re.UNICODE)
_SENTINEL_COMPANIES = {
    "",
    "company page",
    "no company page",
    "none",
    "not listed",
    "unknown",
}


@dataclass(frozen=True)
class AcceptedSourceRow:
    source_row_number: int
    source_record_hash: str
    posting_group_hash: str
    title: str
    source_company: str
    source_location: str
    raw_jd: str
    source_metadata: dict[str, Any]


def display_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", text).strip()


def canonical_text(value: Any) -> str:
    return _WHITESPACE.sub(" ", display_text(value)).casefold()


def _canonical_array_sha256(values: Iterable[str]) -> str:
    payload = json.dumps(
        list(values),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_hash(row: Mapping[str, str], fieldnames: list[str]) -> str:
    return _canonical_array_sha256(canonical_text(row.get(field)) for field in fieldnames)


def _source_metadata(row: Mapping[str, str], source_row_number: int) -> dict[str, Any]:
    return {
        "source_row_number": source_row_number,
        "source_company": display_text(row.get("Co_Nm")),
        "source_location": display_text(row.get("loc")),
        "domain": display_text(row.get("domain")) or None,
        "max_sal": display_text(row.get("max_sal")) or None,
        "med_sal": display_text(row.get("med_sal")) or None,
        "min_sal": display_text(row.get("min_sal")) or None,
        "py_prd": display_text(row.get("py_prd")) or None,
        "visa_sponsor_provenance": "synthetic_scenario",
    }


def read_accepted_rows(
    source_path: Path,
    *,
    expected_count: int = ACCEPTED_ROW_COUNT,
) -> tuple[list[AcceptedSourceRow], dict[str, int]]:
    accepted: list[AcceptedSourceRow] = []
    rejections: Counter[str] = Counter()
    seen: set[tuple[str, str, str, str]] = set()

    with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        required = {"Co_Nm", "Job_Ttl", "Job_Desc", "loc"}
        missing = sorted(required.difference(fieldnames))
        if missing:
            raise ValueError(f"source CSV missing required columns: {', '.join(missing)}")

        for source_row_number, row in enumerate(reader, start=1):
            title = display_text(row.get("Job_Ttl"))
            company = display_text(row.get("Co_Nm"))
            location = display_text(row.get("loc"))
            raw_jd = display_text(row.get("Job_Desc"))
            if not title:
                rejections["empty_title"] += 1
                continue
            if not location:
                rejections["empty_location"] += 1
                continue
            if canonical_text(company) in _SENTINEL_COMPANIES:
                rejections["sentinel_company"] += 1
                continue
            canonical_jd = canonical_text(raw_jd)
            # Historical 31,879-row migration gate treats the boundary as
            # strictly over 300, despite the prose saying "at least 300".
            if len(canonical_jd) <= 300:
                rejections["jd_not_over_300_chars"] += 1
                continue
            canonical_key = (
                canonical_text(company),
                canonical_text(title),
                canonical_text(location),
                canonical_jd,
            )
            if canonical_key in seen:
                rejections["duplicate_canonical_job"] += 1
                continue
            seen.add(canonical_key)
            accepted.append(
                AcceptedSourceRow(
                    source_row_number=source_row_number,
                    source_record_hash=_source_hash(row, fieldnames),
                    posting_group_hash=_canonical_array_sha256(
                        (canonical_key[0], canonical_key[1], canonical_key[3])
                    ),
                    title=title,
                    source_company=company,
                    source_location=location,
                    raw_jd=raw_jd,
                    source_metadata=_source_metadata(row, source_row_number),
                )
            )

    if len(accepted) != expected_count:
        raise ValueError(
            f"accepted row count mismatch: got {len(accepted)}, expected {expected_count}; "
            f"rejections={dict(sorted(rejections.items()))}"
        )
    return accepted, dict(sorted(rejections.items()))


def assign_country_codes(
    source_record_hashes: Iterable[str],
    *,
    cn_quota: int = CN_COUNTRY_QUOTA,
) -> dict[str, str]:
    unique_hashes = set(source_record_hashes)
    if len(unique_hashes) < cn_quota:
        raise ValueError("CN quota exceeds the number of unique records")
    ordered = sorted(
        unique_hashes,
        key=lambda value: hashlib.sha256(value.encode("ascii")).hexdigest(),
    )
    cn_hashes = set(ordered[:cn_quota])
    return {value: ("CN" if value in cn_hashes else "UK") for value in unique_hashes}


def is_visa_sponsor(source_record_hash: str, country_code: str) -> bool:
    threshold = 5 if country_code == "CN" else 35
    bucket_hash = hashlib.sha256(
        f"visa:{source_record_hash}".encode("ascii")
    ).hexdigest()
    return int(bucket_hash, 16) % 100 < threshold


def _role_cluster(title: str, raw_jd: str) -> str:
    text = f"{title} {raw_jd[:4000]}".casefold()
    if any(term in text for term in ("machine learning", "data scientist", "artificial intelligence", " ai ")):
        return "data_ai"
    if any(term in text for term in ("software", "developer", "engineer", "programmer")):
        return "software_engineering"
    if any(term in text for term in ("finance", "bank", "account", "audit")):
        return "finance"
    if any(term in text for term in ("health", "clinical", "medical", "pharma")):
        return "healthcare"
    if any(term in text for term in ("sales", "marketing", "business development")):
        return "marketing_sales"
    if any(term in text for term in ("operation", "supply chain", "logistics")):
        return "operations"
    return "other"


def _converted_row(item: AcceptedSourceRow, country_code: str) -> dict[str, str]:
    pool = CN_COMPANIES if country_code == "CN" else UK_COMPANIES
    locations = CN_LOCATIONS if country_code == "CN" else UK_LOCATIONS
    company_index = int(item.source_record_hash[:8], 16) % len(pool)
    location_index = int(item.source_record_hash[8:16], 16) % len(locations)
    company = pool[company_index]
    location = locations[location_index]
    visa_sponsor = is_visa_sponsor(item.source_record_hash, country_code)
    metadata = dict(item.source_metadata)
    metadata.update(
        {
            "synthetic_company": company,
            "synthetic_location": location,
            "country_code": country_code,
            "visa_sponsor": visa_sponsor,
        }
    )
    raw_jd = f"演示背景：{company}，工作地点 {location}。\n{item.raw_jd}"
    return {
        "job_id": f"linkedin-cnuk:{item.source_record_hash}",
        "source_record_hash": item.source_record_hash,
        "posting_group_hash": item.posting_group_hash,
        "title": item.title,
        "company": company,
        "location": location,
        "country_code": country_code,
        "visa_sponsor": "true" if visa_sponsor else "false",
        "demo_synthetic": "true",
        "source_tag": DATASET_ID,
        "role_cluster": _role_cluster(item.title, item.raw_jd),
        "is_open": "false",
        "degree_required": "unknown",
        "min_years_exp": "",
        "responsibilities": "",
        "required_skills": "[]",
        "nice_to_have": "[]",
        "deadline": "",
        "salary_min": "",
        "salary_max": "",
        "raw_jd": raw_jd,
        "source_metadata": json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _chunk_count(rows: list[dict[str, str]]) -> int:
    total = 0
    for row in rows:
        chunk_source = {
            "title": row["title"],
            "company": row["company"],
            "location": row["location"],
            "role_cluster": row["role_cluster"],
            "degree_required": row["degree_required"],
            "min_years_exp": None,
            "responsibilities": None,
            "required_skills": [],
            "nice_to_have": [],
            "raw_jd": row["raw_jd"],
        }
        total += len(_build_chunk_specs(chunk_source))
    return total


def _collision_report(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = Counter((row["company"], row["title"], row["location"]) for row in rows)
    collisions = [count for count in counts.values() if count > 1]
    return {
        "collision_key_count": len(collisions),
        "colliding_row_count": sum(collisions),
        "excess_row_count": sum(count - 1 for count in collisions),
        "max_collision_size": max(collisions, default=0),
    }


def transform_corpus(
    source_path: Path,
    output_path: Path,
    manifest_path: Path,
    *,
    expected_count: int = ACCEPTED_ROW_COUNT,
    cn_quota: int = CN_COUNTRY_QUOTA,
    embedding_fingerprint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    accepted, rejection_counts = read_accepted_rows(
        source_path,
        expected_count=expected_count,
    )
    countries = assign_country_codes(
        (item.source_record_hash for item in accepted),
        cn_quota=cn_quota,
    )
    rows = sorted(
        (
            _converted_row(item, countries[item.source_record_hash])
            for item in accepted
        ),
        key=lambda row: row["job_id"],
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    with output_tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=OUTPUT_FIELDS,
            lineterminator="\n",
            extrasaction="raise",
        )
        writer.writeheader()
        writer.writerows(rows)
    output_tmp.replace(output_path)

    country_counts = Counter(row["country_code"] for row in rows)
    visa_counts = Counter(
        row["country_code"] for row in rows if row["visa_sponsor"] == "true"
    )
    chunk_count = _chunk_count(rows)
    fingerprint = {
        "model": None,
        "dimension": None,
        "splitter_version": None,
        "build_id": None,
    }
    if embedding_fingerprint is not None:
        fingerprint.update(dict(embedding_fingerprint))
    manifest = {
        "manifest_version": "cnuk_demo_manifest_v1",
        "dataset_id": DATASET_ID,
        "transform_version": TRANSFORM_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "source_file": {
            "name": source_path.name,
            "bytes": source_path.stat().st_size,
            "sha256": _file_sha256(source_path),
            "row_count": expected_count + sum(rejection_counts.values()),
        },
        "output_file": {
            "name": output_path.name,
            "bytes": output_path.stat().st_size,
            "sha256": _file_sha256(output_path),
        },
        "row_count": len(rows),
        "chunk_count": chunk_count,
        "embedding_batch_size": 10,
        "projected_embedding_requests": math.ceil(chunk_count / 10),
        "country_counts": {
            "CN": country_counts.get("CN", 0),
            "UK": country_counts.get("UK", 0),
        },
        "visa_sponsor": {
            country: {
                "true_count": visa_counts.get(country, 0),
                "ratio": round(
                    visa_counts.get(country, 0) / country_counts[country], 6
                ),
            }
            for country in ("CN", "UK")
            if country_counts[country]
        },
        "rejection_counts": rejection_counts,
        "collisions": _collision_report(rows),
        "embedding_fingerprint": fingerprint,
        "synthetic_fields": ["company", "location", "visa_sponsor"],
        "salary_policy": "source_values_only_in_source_metadata_no_display_range",
        "serialization": "utf-8-no-bom,rfc4180,comma,lf,fixed-columns",
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    manifest_tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    manifest_tmp.replace(manifest_path)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    manifest = transform_corpus(args.input, args.output, args.manifest)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
