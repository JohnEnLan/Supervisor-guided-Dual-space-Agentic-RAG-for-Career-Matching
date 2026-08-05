# W5 CN/UK demo corpus validation

Dataset: `linkedin_ml_cnuk_demo_v1`

## Deterministic conversion

- Source: user-supplied local `LinkedInJobs_MLDataset.csv`, 33,246 rows, 130,289,473 bytes.
- Source SHA-256: `25c32abb828fa8e4505544af35c26ec3c5a2f0b292093ff56c96525e6d8f1b0b`.
- Accepted: 31,879 rows; CN 22,315, UK 9,564.
- Rejected: 703 company sentinels, 228 JD boundary/short rows, 436 duplicate canonical jobs.
- Historical-count compatibility note: the prose design says “at least 300” and names four company sentinels. The supplied file reaches its separately mandated 31,879 gate only when the two `Company Page` pseudo-companies are also treated as unnamed and the single exactly-300-character canonical JD is excluded. These two edge rules are explicit in code and tests; no arbitrary hash-ranked rows are removed.
- Output: 145,707,043 bytes; SHA-256 `5aa0d87160d9bcf894173b6d44dd03f97a1819632adf8f84519e35d81d6c899b`.
- Byte replay: two independent transformations produced identical CSV and pre-freeze manifest bytes.
- Post-transform chunks: 120,584; projected batch-10 embedding requests: 12,059.
- Display collisions `(company,title,location)`: 102 keys / 204 rows / 102 excess rows; maximum group size 2. No row was removed.
- Visa scenario: CN 1,067 true (4.7815%); UK 3,272 true (34.2116%).
- Synthetic fields are limited to company, location, and visa sponsorship. Salary source values remain only in `source_metadata`; no CNY/GBP range is generated.

## Embedding fingerprint

- Model: `text-embedding-v4`
- Dimension: 1,024
- Splitter: `load_jobs_splitter_v1:max_chars=1800:67138f974667da3d`
- Build ID: `cnuk_demo_embedding_v1`

## Real PostgreSQL and DashScope pilots

Migration `0006_demo_corpus.sql` applied to local PostgreSQL 17.10. First application recorded the migration; immediate second application applied zero files. All four job columns and `job_import_windows` were verified.

| Stage | Jobs | Chunks | Windows | First-run time | Resume verification |
|---|---:|---:|---:|---:|---|
| Trial | 100 | 396 | 1 | 6.333 s | rerun skipped 1/1 window; then 100 jobs and 396 chunks cleaned |
| Preview | 3,000 | 11,372 | 6 | 159.376 s | rerun skipped 6/6 windows in 0.022 s |

Preview validation: 0 open jobs, 0 rows missing `demo_synthetic`, 0 null/wrong-dimension vectors, all six windows succeeded on their first window attempt. The preview remains staged in the formal tables with `is_open=false`.

At preview throughput, the chunk-scaled estimate for 120,584 chunks is about 1,689 seconds (28.2 minutes). Allowing for API and database variability, the operator budget should reserve roughly 28–35 minutes. The full import was not started.

## Cutover rehearsal

With zero queued/running runs, a single transaction flipped the 3,000-row preview forward and then executed the rollback direction. Post-transaction state was verified as restored: 50 legacy rows open, 0 demo rows open, 3,000 demo rows closed.

## Artifact location constraint

The managed Codex sandbox denied writes to the requested external sibling directory. The real converted CSV and operational manifest therefore remain in the repository's already-untracked `outputs/w5/` directory for this run; neither is part of the git change set. The checked-in manifest above contains hashes/counts only, never source/JD contents or credentials.
