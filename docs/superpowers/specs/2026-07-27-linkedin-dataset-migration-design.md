# LinkedIn 31,879-Job Dataset Migration Design

## 1. Goal

Replace the active 2023 LinkedIn sample with a recoverable, provenance-aware
31,879-job research corpus derived from:

`C:\Users\WIN11\Desktop\linkedin-jobs-machine-learning-data-set\LinkedInJobs_MLDataset.csv`

The migration must:

- archive the old files and database rows before any persistent write;
- import and validate a deterministic 100-job trial first;
- import all 31,879 accepted jobs with resumable, idempotent batches;
- build field-aware chunks and RAPTOR-lite indexes;
- verify English and Chinese-to-English retrieval;
- delete the old active corpus only after every acceptance gate passes; and
- preserve enough information and commands to restore the old state.

The migration does not claim that the source postings are currently open. The
source CSV has no posting date, expiry date, closed status, or source URL.

## 2. Scope and Non-Goals

### In scope

- A recoverable archive and SHA-256 migration manifest.
- Typed provenance on imported jobs.
- Deterministic conversion without one DeepSeek call per JD.
- A 100-job trial import.
- A full 31,879-job import.
- Qwen `text-embedding-v4` chunk embeddings at 1,024 dimensions.
- RAPTOR-lite job summaries, role summaries, and leaf mappings.
- English BM25/dense/RAPTOR smoke tests.
- Chinese resume text against English JD dense/RAPTOR smoke tests.
- Transactional deletion of the old database corpus and removal of old active
  dataset/evaluation files.

### Out of scope

- Claiming that an imported job is still open.
- Fabricating visa, education, experience, salary, industry, or deadline data.
- Calling DeepSeek once for every imported JD.
- Creating artificial relevance labels for the new corpus.
- Full recursive RAPTOR or cross-encoder reranking.
- Treating application domains such as Greenhouse or SmartRecruiters as
  employer industries.
- Deleting user feedback, match history, or session state that happens to
  reference an old job. The cleanup must stop for review if such dependencies
  exist.

## 3. Accepted Source Rows

The source contains 33,246 rows. The accepted corpus is exactly 31,879 rows.
The converter applies these rules in order:

1. Normalize title, company, location, and JD whitespace.
2. Require a non-empty title.
3. Require a non-empty location.
4. Require a named company, excluding blank values and the sentinel values
   `No Company Page`, `None`, `Unknown`, and `Not Listed`.
5. Require a normalized JD length of at least 300 Unicode characters.
6. Deduplicate on the case-folded tuple
   `(company, title, location, normalized_jd)`, keeping the first source row.
7. Sort the result by generated `job_id`.

The conversion command must fail without writing output if the accepted count
is not exactly 31,879.

Repeated postings with the same company, title, and JD but different locations
remain separate jobs. The converter assigns them the same
`posting_group_hash`. Retrieval diversification may later cap a group in Top-K,
but the migration does not erase genuine location variants.

## 4. Architecture

The migration uses one active PostgreSQL database and source-tagged batches.
It does not build a second database or overwrite the old corpus in place.

The phases are:

1. Read-only preflight.
2. Archive and restore verification.
3. Schema/provenance migration.
4. Deterministic source conversion.
5. Trial import of 100 jobs.
6. Trial chunk, embedding, RAPTOR, and retrieval verification.
7. Resumable full import of 31,879 jobs.
8. Full chunk and RAPTOR build.
9. Full validation.
10. Transactional old-database cleanup.
11. Removal of old active files and evaluation cache.

Every phase records its status in the import batch record. A failed phase never
automatically advances to the next phase.

## 5. Archive and Recovery

No schema or data write may occur until the archive is complete and verified.

The archive directory is:

`backups/job-migration-<UTC timestamp>/`

It contains:

- the five active `data/jobs/*_1000.csv` files;
- `data/eval/evaluation_manifest.json`;
- `data/eval/relevance_labels.jsonl`;
- `data/eval/resume_queries.jsonl`;
- `data/eval/offline_lexical_rankings_1000.json`;
- JSONL exports of the current `jobs`, `job_chunks`, and `raptor_nodes` rows;
- an export of `raptor_node_chunks` when that table exists;
- a dependency report for every table or JSON artifact that references an old
  job ID;
- `restore.ps1` with explicit restore commands; and
- `manifest.json`.

`manifest.json` records:

- archive format version;
- UTC creation time;
- Git commit and branch;
- source and destination database identifiers without credentials;
- every archived path, byte count, row count, and SHA-256;
- the old job ID list;
- database counts expected at archive time;
- restore ordering; and
- archive verification status.

The expected old database baseline is 50 jobs, 280 chunks, and 58 RAPTOR nodes.
The preflight records actual counts and stops if they differ, so later cleanup
never relies on stale assumptions.

Archive verification performs three checks:

1. Recompute and compare every SHA-256.
2. Parse every JSON/JSONL export and reconcile row counts.
3. Restore the database exports into temporary verification tables inside a
   transaction and roll the transaction back.

The archive directory is local recovery material and is not committed to Git.
The manifest and restoration logs must not include API keys or the database
password.

## 6. Database Provenance

The `jobs` table gains:

- `source_dataset TEXT`;
- `import_batch_id TEXT`;
- `source_record_hash TEXT`;
- `posting_group_hash TEXT`;
- `source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb`; and
- `imported_at TIMESTAMPTZ`.

The old loaded jobs are tagged with the old dataset identifier before trial
import. The new dataset identifier is a stable logical name, not a claim about
the collection date.

A `job_import_batches` table records:

- `batch_id`;
- `source_dataset`;
- source path and source SHA-256;
- expected and accepted row counts;
- status and current phase;
- last completed `job_id`;
- jobs, chunks, RAPTOR nodes, and mappings written;
- error code and error detail;
- creation, update, and completion timestamps.

Status transitions are bounded and explicit:

`created -> archived -> converted -> trial_validated -> importing -> indexed -> validated -> cutover_complete`

A failure sets `status = failed` and preserves the checkpoint. Rerunning the
same batch resumes from the last completed stable `job_id`.

## 7. Stable IDs and Field Mapping

`job_id` is:

`linkedin-ml:` followed by the full SHA-256 hex digest of the canonical
`company`, `title`, `location`, and normalized JD joined with a unit separator.

The same canonical digest is stored as `source_record_hash`. A second digest of
canonical `company`, `title`, and normalized JD is stored as
`posting_group_hash`.

Direct mappings are:

- `Co_Nm -> company`;
- `Job_Ttl -> title`;
- `Job_Desc -> raw_jd`;
- `loc -> location`.

The remaining source columns are preserved in `source_metadata`, including
company employee/follower counts, work type, experience level, remote flag,
salary values, pay period, views, application type, and posting domain.

Derived fields use deterministic rules:

- `role_cluster` uses the repository's allowed role taxonomy with title-first,
  JD-second keyword routing and a final `other` fallback;
- `is_open = NULL`;
- `deadline = NULL`;
- `visa_sponsor = NULL`;
- `min_years_exp = NULL` unless an unambiguous deterministic rule is later
  separately specified and tested;
- `degree_required = 'unknown'`;
- `responsibilities = NULL`;
- `required_skills = []`;
- `nice_to_have = []`.

The importer never turns missing evidence into a positive or negative fact.

## 8. Open/Unknown Retrieval Semantics

The existing retrieval and RAPTOR filters use `is_open = TRUE`. They change to:

`is_open IS DISTINCT FROM FALSE`

This includes confirmed-open and unknown snapshot records while excluding
confirmed-closed jobs. User-facing output must treat a NULL value as
dataset-only/unverified and must not display an Apply action or claim that the
job is currently open.

## 9. Chunking and Embedding

The accepted 31,879 rows produce, with the current 1,800-character splitter:

- 31,879 metadata chunks;
- 88,369 raw-JD chunks;
- exactly 120,248 minimum chunks; and
- an average of 3.77 chunks per job.

Because deterministic import leaves responsibilities and skill arrays empty,
the initial build contains metadata and raw-JD chunks only. Later enrichment
may add structured chunks in a separate, versioned job.

Embedding requirements:

- model: `text-embedding-v4`;
- dimension: 1,024;
- API batch size: at most 10 texts;
- bounded concurrent batches controlled by the existing embedding semaphore;
- bounded retries with recorded failures;
- no construction of tens of thousands of unbounded coroutines; and
- checkpoint commits by stable job-ID windows.

Re-running a completed chunk window replaces the same stable chunk IDs and does
not increase counts.

## 10. RAPTOR-lite Compatibility

The imported jobs are compatible with the existing RAPTOR-lite design after
their chunks exist.

The builder must:

- ensure `raptor_nodes` and `raptor_node_chunks` exist;
- accept a `source_dataset` or explicit job-ID filter;
- build one job-summary node for each imported job;
- build at most one role-summary node for each of the 11 allowed role clusters;
- write job-to-chunk and role-to-chunk mappings;
- delete stale nodes and mappings for the same source dataset before marking
  the build complete; and
- remain optional in ordinary P0 retrieval.

Expected scale:

- 31,879 job-summary nodes;
- at most 11 role-summary nodes;
- at most 31,890 total RAPTOR nodes; and
- approximately 240,496 mapping rows because each chunk maps to its job node
  and one role node.

RAPTOR does not replace BM25 or dense retrieval. It remains an optional
ablation/retrieval source.

## 11. Trial Import

The trial contains exactly 100 accepted jobs selected deterministically across
non-empty role clusters. The selection is stable for the source SHA-256 and
must include data/AI, software, finance, healthcare, engineering, sales, and
operations examples when those clusters are present.

Trial acceptance gates:

1. The archive is verified.
2. Exactly 100 source-tagged jobs exist for the trial batch.
3. Re-running the job import changes no row count or stable ID.
4. Every trial job has at least one metadata and one JD chunk.
5. Every embedding is finite and 1,024-dimensional.
6. There are no orphan chunks.
7. There is one RAPTOR job node per trial job, non-empty role nodes, and no
   orphan RAPTOR mappings.
8. An English query returns relevant English JDs through BM25 and dense
   retrieval with evidence spans.
9. The same English query works with RAPTOR enabled.
10. A Chinese resume/query for a represented role returns English JDs from the
    matching role cluster in Top-10 through dense retrieval.
11. The Chinese query also returns evidence-bearing results with RAPTOR
    enabled.
12. A second trial run produces identical counts and IDs.

The already executed model-level smoke test is necessary but not sufficient:
`text-embedding-v4` returned three finite 1,024-dimensional vectors, and the
Chinese/English equivalent pair scored above the unrelated pair. Trial
acceptance still requires real imported JD retrieval.

## 12. Full Import and Validation

The full import resumes the same logical source dataset after trial validation.
The 100 trial jobs are upserted as part of the 31,879 total; they are not added
on top.

Full validation requires:

- exactly 31,879 new source-tagged jobs;
- exactly 31,879 distinct stable job IDs;
- no rejected sentinel company names;
- no JD shorter than 300 normalized characters;
- no duplicate canonical job keys;
- exactly 120,248 initial chunks unless the checked-in splitter changes before
  execution, in which case the converter records and tests the new
  deterministic expected count;
- no orphan chunks;
- all embeddings finite and 1,024-dimensional;
- one RAPTOR job node per imported job;
- role-node and mapping counts reconciled with source clusters and chunks;
- HNSW and GIN indexes present;
- English BM25, dense, and RAPTOR smoke tests pass;
- Chinese-to-English dense and RAPTOR Top-10 smoke tests pass;
- retrieval evidence IDs resolve to the returned job's chunks;
- rerunning the full batch is idempotent; and
- the existing automated test suite passes.

These smoke tests do not replace Recall@K, Precision@K, MRR, or NDCG. Those
metrics remain unavailable for the new corpus until new relevance labels are
manually created.

## 13. Cutover and Old-Corpus Cleanup

Cleanup begins only after every full validation gate passes and the archive is
re-verified.

A read-only dependency check enumerates foreign keys and known JSON/text
references to old job IDs. If any user feedback, case outcome, match history, or
session state depends on an old job, cleanup stops and reports the exact
dependency. It does not silently delete or rewrite user state.

When dependency checks are clear, one database transaction deletes, in order:

1. old `raptor_node_chunks` rows;
2. old job-summary nodes and stale old role-node references;
3. old `job_chunks`;
4. old `jobs`; and
5. old import-batch metadata that is explicitly part of the archived corpus.

The transaction rolls back on any count mismatch.

After the transaction commits:

- remove the five active `data/jobs/*_1000.csv` files;
- remove the old active lexical ranking cache;
- archive and remove the old corpus-bound relevance labels and manifest;
- retain or copy the query texts only as an unlabeled seed set under a new
  filename;
- create a new corpus manifest with `labels_status = pending_manual_annotation`;
  and
- recompute active file hashes.

The local archive remains untouched. Restoration uses `restore.ps1` and the
archived manifest.

## 14. Error Handling and Safety

- Every destructive target is resolved to an explicit old job-ID list from the
  verified archive manifest.
- No destructive SQL uses a wildcard source name or an unresolved environment
  variable.
- Every external call uses the existing semaphore and a timeout.
- Retry loops are bounded.
- Failed rows are recorded with stable IDs and error classes.
- A failed window can be retried without duplicating jobs, chunks, or nodes.
- Old data remains active until full validation succeeds.
- File deletion occurs only after the database cleanup transaction commits.
- The archive is never deleted by this migration.

## 15. Testing Strategy

Implementation follows test-driven development.

Unit tests cover:

- canonical normalization and stable hashes;
- the exact 31,879-row acceptance count;
- sentinel company rejection;
- 300-character JD threshold;
- deterministic deduplication;
- field mapping and unknown-value preservation;
- batch state transitions;
- checkpoint resume behavior;
- open/unknown SQL semantics;
- source-filtered chunk and RAPTOR builds; and
- cleanup target resolution.

Integration tests cover:

- archive/export/restore verification;
- 100-job idempotent import;
- chunk and embedding reconciliation;
- RAPTOR mappings;
- English hybrid retrieval;
- Chinese-to-English dense/RAPTOR retrieval;
- full-count reconciliation; and
- cleanup rollback on dependency or count mismatch.

Live Qwen calls are limited to explicit integration commands. Normal unit tests
use deterministic test doubles and never consume API quota.

## 16. Completion Criteria

The migration is complete only when:

- the verified archive and restoration instructions exist;
- the 31,879-job corpus, 120,248 initial chunks, and RAPTOR indexes reconcile;
- English and Chinese retrieval gates pass;
- a repeat import produces no duplicate rows;
- old database records and active files are removed only after validation;
- the new manifest accurately states that freshness and labels are unknown;
- the test suite passes; and
- the final report lists actual counts, timings, failures, API calls, and any
  remaining limitations.
