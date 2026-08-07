# LinkedIn 31,879-Job Dataset Migration Design

## 1. Goal

Replace the active 2023 LinkedIn sample with a recoverable, provenance-aware
31,879-job research corpus derived from:

`C:\Users\WIN11\Desktop\linkedin-jobs-machine-learning-data-set\LinkedInJobs_MLDataset.csv`

The migration must:

- archive and verify the old state and new deterministic input before any
  committed application-schema, application-data, or active-corpus write;
- import and validate a deterministic 100-job trial first;
- import all 31,879 accepted jobs with resumable, idempotent batches;
- build all field-aware chunks and prove RAPTOR-lite compatibility on the
  trial, with a separately gated optional full RAPTOR build;
- verify English and Chinese-to-English retrieval;
- delete the old active corpus only after every acceptance gate passes; and
- preserve enough information and commands to restore the old state.

The migration does not claim that the source postings are currently open. The
source CSV has no posting date, expiry date, closed status, or source URL.

## 2. Scope and Non-Goals

### In scope

- A recoverable archive and SHA-256 migration manifest.
- An immutable local copy of the new source CSV and converted accepted corpus.
- Typed provenance on imported jobs.
- Deterministic conversion without one DeepSeek call per JD.
- A 100-job trial import.
- A full 31,879-job import.
- Qwen `text-embedding-v4` chunk embeddings at 1,024 dimensions.
- RAPTOR-lite job summaries, role summaries, and leaf mappings for the
  independent 100-job research trial and optional full P2 build.
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
- Publishing or redistributing the source dataset. Its license and original
  collection provenance are not present in the supplied folder, so the
  migration records `license_status = unknown` and keeps all source copies
  local and untracked.

## 3. Accepted Source Rows

The source contains 33,246 rows. The accepted corpus is exactly 31,879 rows.
Canonicalization version `linkedin_ml_canonical_v1` defines:

- display fields: Unicode NFC, normalized line endings, trimmed outer
  whitespace, original letter case preserved;
- canonical fields: display-field text with every Unicode whitespace run
  replaced by one ASCII space, followed by Unicode case-folding; and
- canonical JD length: the number of Unicode code points in the canonical JD.

`raw_jd` stores the display JD. Hashes, deduplication, and the 300-character
threshold use the canonical JD. The existing chunk splitter receives
`raw_jd`; its `_compact_text` step deterministically collapses whitespace before
splitting, so line-ending preservation does not change the expected chunk
count.

All converted artifacts use a fixed serialization contract: UTF-8 without
BOM, RFC 4180 CSV quoting, comma delimiter, LF line endings, fixed column
order, explicit JSON `null`, and typed fields defined by a checked-in data
schema. Hash inputs are RFC 8785 JSON Canonicalization Scheme (JCS) arrays
encoded as UTF-8, not delimiter-joined free text. The implementation forbids
NaN/Infinity and records its JCS library/version fingerprint.

The converter applies these rules in order:

1. Build display and canonical values using `linkedin_ml_canonical_v1`.
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

The canonicalization implementation and ordered role-routing rules have
version constants and SHA-256 fingerprints. Both fingerprints are stored in
the converted-corpus manifest and import-batch record.

Repeated postings with the same company, title, and JD but different locations
remain separate jobs. The converter assigns them the same
`posting_group_hash`. Retrieval diversification may later cap a group in Top-K,
but the migration does not erase genuine location variants.

## 4. Architecture

The migration uses one active PostgreSQL database and source-tagged batches.
It does not build a second database or overwrite the old corpus in place.

The phases are:

1. Read-only preflight.
2. Old-state rollback package and restore verification.
3. Deterministic source conversion, immutable input package, and byte-identical
   input replay verification.
4. Capacity and external-call budget gate.
5. Schema/provenance migration.
6. Trial import of 100 non-public jobs and vectors into physically separate
   staging tables.
7. P0 trial chunk, embedding, BM25/dense, and English/Chinese verification.
8. Resumable full import of 31,879 jobs and chunks into the staging tables.
9. Full P0 jobs/chunks/BM25/dense validation.
10. Transactional copy into the production tables, eligibility cutover, and
    old-database cleanup.
11. Removal of old active files and evaluation cache.
12. Independent RAPTOR-lite research branch: a 100-job mechanism test and an
    optional, separately recoverable full build. Neither blocks P0.

Before the control tables exist, phases 1--4 record progress in an append-only
`pre-schema-journal.jsonl` inside the archive directory. Each entry includes
the previous-entry hash, current-entry SHA-256, phase, inputs, result, and UTC
time. The hash is SHA-256 over the RFC 8785 canonical payload after removing
`entry_sha256`; the first `previous_entry_sha256` is 64 ASCII zeroes. The digest
is then attached to the record. After both packages and the top-level manifest
are verified and the schema migration commits, the journal's verified state is
imported into the batch row. Subsequent phases record status in the database.
A failed phase never automatically advances.

## 5. Archive and Recovery

No committed application-schema, application-data, or active-corpus write may
occur until `rollback.zip`, `input.zip`, and the top-level manifest are all
complete and verified. This includes input replay producing byte-identical
converted output and the same stable IDs. `converted` means this replay gate
has passed; `schema_ready` cannot be entered without all three verified
artifacts. Verification may use PostgreSQL temporary tables inside a
transaction that always rolls back.

The archive directory is:

`backups/job-migration-<UTC timestamp>/`

It contains two independently hashed packages.

`rollback.zip` is created and verified first. It contains:

- the five active `data/jobs/*_1000.csv` files;
- `data/jobs/linkedin_1000_manifest.txt`;
- `data/eval/evaluation_manifest.json`;
- `data/eval/relevance_labels.jsonl`;
- `data/eval/resume_queries.jsonl`;
- `data/eval/offline_lexical_rankings_1000.json`;
- every additional corpus-bound artifact discovered from the evaluation manifest
  or by matching archived old job IDs;
- the schema DDL and migration version needed to restore the old tables;
- JSONL exports of the current `jobs`, `job_chunks`, and `raptor_nodes` rows,
  with pgvector values serialized as bracketed text;
- an equivalent export of `raptor_node_chunks` when that table exists;
- a dependency report for every table or JSON artifact that references an old
  job ID;
- `restore.ps1` with explicit restore commands; and
- `rollback-manifest.json`.

`input.zip` is created after deterministic conversion and before any trial
database write. It contains:

- the exact user-supplied `LinkedInJobs_MLDataset.csv`;
- its data dictionary;
- the canonical 31,879-row converted CSV;
- the rejected-row report with rule codes;
- the deterministic 100-job trial-ID manifest;
- the versioned retrieval smoke-test manifest; and
- `input-manifest.json`.

The top-level `manifest.json` records:

- archive format version;
- UTC creation time;
- Git commit and branch;
- source and destination database identifiers without credentials;
- every archived path, byte count, row count, and SHA-256;
- the old job ID list;
- database counts expected at archive time;
- restore ordering; and
- archive verification status;
- SHA-256 and byte count for both ZIP packages;
- `source_origin = user_supplied_local_file`;
- `license_status = unknown`;
- `redistribution_allowed = false`; and
- canonicalization, role-router, chunking, embedding-model, embedding-dimension,
  and index-build versions;
- SHA-256 fingerprints of the converter implementation, typed output schema,
  role-router table, splitter implementation and configuration, and smoke-test
  manifest; and
- the fixed CSV/JSON serialization contract.

The expected old database baseline is 50 jobs, 280 chunks, and 58 RAPTOR nodes.
The preflight records actual counts and stops if they differ, so later cleanup
never relies on stale assumptions.

`restore.ps1` has two explicit modes:

- `-Mode ReactivateLegacy` targets the migrated schema. It restores archived
  rows with explicit column lists, moves any new production chunks and RAPTOR
  rows back to batch staging before removing them from production indexes,
  deactivates the new jobs, marks the exact archived old job IDs eligible, and
  restores old production chunks and optional RAPTOR rows. By default the new
  jobs and staged vectors are preserved but physically isolated; `-PurgeNew`
  is allowed only after the same dependency checks used by cleanup.
- `-Mode RebuildLegacyDatabase` restores the archived pre-migration DDL and
  rows into an empty recovery database. It never attempts to replace shared
  user-state tables in a live database.

Forward cutover, cleanup, and `ReactivateLegacy` run under database-backed
maintenance mode. The API returns a retryable maintenance response and the
evaluation CLI refuses to run while that flag is set. Corpus/evaluation files
live in versioned bundle directories; code resolves one small
`active-corpus.json` pointer rather than hard-coded active files. A prepared
bundle is fully hash-checked before the pointer is replaced atomically on the
same volume.

`ReactivateLegacy` is an idempotent two-medium state machine:

1. take the exclusive corpus advisory lock, enter maintenance mode, increment
   `corpus_epoch`, and invalidate prior-epoch task writers;
2. prepare and verify the complete legacy file bundle without activating it;
3. in one database transaction, physically isolate new vectors, restore old
   rows with explicit columns, restore old eligibility, keep maintenance mode
   set, verify archived counts, and persist
   `active_source_dataset = linkedin_kaggle_2023_sample_v1`, the verified
   legacy pointer payload SHA-256, and
   `recovery_phase = db_restore_committed`;
4. atomically replace `active-corpus.json` with the legacy-bundle pointer; and
5. in a final database transaction, recheck the pointer hash and database
   counts, set `recovery_phase = restore_complete`, and leave maintenance mode.

If any step fails, the service stays in maintenance mode and rerunning resumes
from a database recovery-phase record. Public service is never enabled between
the database and file phases.

Rollback-package verification performs five checks:

1. Recompute and compare every SHA-256.
2. Parse every JSON/JSONL export and reconcile row counts.
3. Restore the database exports into PostgreSQL temporary verification tables
   inside a transaction and roll the transaction back.
4. Reconcile restored vectors and arrays: embeddings are loaded from text with
   an explicit `::vector` cast, arrays use JSON arrays, and `tsvector` values
   are regenerated from archived content rather than serialized.
5. In an isolated recovery database migrated to the post-migration schema,
   seed a representative cutover state and run the complete
   `restore.ps1 -Mode ReactivateLegacy`; require the old public candidate set,
   eligibility, database counts, and active file hashes to match the archive
   while the new corpus jobs are hidden and its vectors are absent from
   production indexes.

Input-package verification recomputes file hashes, reruns conversion from the
archived source copy, and requires byte-identical converted output and the same
31,879 stable IDs.

The archive directory is local recovery material and is not committed to Git
or uploaded. The manifest and restoration logs must not include API keys or the
database password.

## 6. Database Provenance

The `jobs` table gains:

- `source_dataset TEXT`;
- `import_batch_id TEXT`;
- `source_record_hash TEXT`;
- `posting_group_hash TEXT`;
- `source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb`;
- `retrieval_eligible BOOLEAN NOT NULL DEFAULT FALSE`;
- `freshness_status TEXT`;
- `imported_at TIMESTAMPTZ`.

The exact logical dataset identifiers are:

- old sample: `linkedin_kaggle_2023_sample_v1`;
- new corpus: `linkedin_jobs_ml_31879_v1`.

The schema migration and old-corpus backfill are one transaction. Using only
the exact archived old job-ID list, it:

1. adds the new columns;
2. tags exactly 50 existing jobs with the old identifier;
3. sets exactly those 50 jobs to `retrieval_eligible = TRUE`;
4. verifies all other pre-existing rows, if any, and stops for review instead
   of changing them; and
5. only then deploys the new public retrieval predicate.

A before/after regression gate requires the same legacy public job count and
candidate IDs for fixed BM25 and dense queries. The new identifier is stable
and deliberately does not claim a collection date.

Trial and full vectors are physically isolated from the production HNSW
indexes. The migration creates batch-scoped `job_chunks_staging`,
`raptor_nodes_staging`, and `raptor_node_chunks_staging` tables with their own
indexes. Internal validation queries name those tables and an exact batch/job
allowlist. Public queries continue to use only `job_chunks` and
`raptor_nodes`; they never scan a staging vector index. The capacity estimate
includes temporary duplicate storage for staging plus production data during
cutover.

A database-backed `retrieval_feature_state` row records the active source
dataset, whether public RAPTOR is enabled, maintenance mode, recovery phase,
the expected active-corpus pointer hash, and a monotonically increasing
`corpus_epoch`. It is read with the rest of the retrieval configuration, never
stored in process-global mutable state.

Every submitted matching task stores the current `corpus_epoch`. Before any
state/result/feedback write that can contain job IDs, the writer takes a shared
PostgreSQL advisory transaction lock and verifies that the epoch is unchanged
and maintenance mode is off. Otherwise it records a retryable
`corpus_changed` outcome without writing stale job references. Cutover takes
the corresponding exclusive advisory lock.

A `job_import_batches` table records:

- `batch_id`;
- `source_dataset`;
- source path and source SHA-256;
- expected and accepted row counts;
- status and current phase;
- the highest contiguous completed window;
- jobs, chunks, RAPTOR nodes, and mappings written;
- canonicalization and role-router versions and SHA-256 fingerprints;
- chunking version plus splitter implementation/configuration SHA-256;
- converter implementation, typed output schema, serialization contract, and
  smoke-test-manifest SHA-256 fingerprints;
- embedding model, requested dimension, and embedding build version;
- projected, reserved-attempt, and consumed embedding requests/tokens;
- configured request and token budgets;
- error code and error detail;
- creation, update, and completion timestamps.

`jobs.import_batch_id` remains nullable only for legacy/other rows. For the new
source dataset, a conditional `CHECK` requires non-null `import_batch_id`,
`source_record_hash`, `posting_group_hash`, `freshness_status`, and
`imported_at`. A unique `(batch_id, source_dataset)` key on
`job_import_batches` and matching composite foreign key from `jobs` prove that
the row and batch identify the same source dataset. The foreign key uses
`ON DELETE RESTRICT`. The migration also creates:

- a unique index on `(source_dataset, source_record_hash)`;
- an index on `(source_dataset, retrieval_eligible)`; and
- an index on `import_batch_id`.

`job_import_windows` records the deterministic start/end job IDs, expected
job/chunk counts, state, external-call attempt counters, actual counts, error,
and completion time for each window. Its primary key is
`(batch_id, window_number)`. A worker claims a pending/failed/expired window
with an atomic lease transition containing `owner_token`, `lease_expires_at`,
and unique `attempt_id`. In the same short transaction it locks the batch row,
checks the remaining request/token limits, and increments a conservative
reservation before any external call. Actual usage is later settled by
`attempt_id`; lease expiry never erases a reservation, and a stale worker may
not commit after ownership changes.

A window's job/chunk/vector upserts,
deletion of stale chunk IDs for jobs in that window, count reconciliation, and
success checkpoint are one database transaction. The contiguous checkpoint is
advanced only across succeeded windows; it is never inferred from the maximum
job ID. External-call budget is reserved and committed before a call, and every
attempt counts even if the later database transaction fails. Cached responses
are keyed by content hash and embedding build fingerprint; otherwise a failed
window may safely replay a call, but it cannot exceed the budget silently.

Status transitions are bounded and explicit:

`created -> archived -> converted -> capacity_approved -> schema_ready -> trial_importing -> trial_p0_validated -> full_importing -> p0_indexed -> p0_validated -> cutover_complete`

The independent RAPTOR research branch has its own states:

`not_started -> raptor_trial_building -> raptor_trial_validated -> raptor_full_building -> raptor_full_validated -> raptor_published`

After the trial report, it may instead transition to `raptor_skipped`; this
state does not change the main P0 batch status.

Before cutover, any nonterminal main state may enter
`aborting -> aborted`. The abort transaction resolves the exact batch ID,
requires every batch job to remain ineligible and dependency-free, deletes its
RAPTOR mappings/nodes and chunk staging rows in FK order, deletes its invisible
jobs, releases live leases, and sets `superseded_by` when a replacement batch
exists. The batch row, window outcomes, attempt ledger, fingerprints, errors,
and consumed/reserved budgets remain immutable audit evidence. A changed
fingerprint always requires a new batch; it is never patched into the old row.

A failure sets `status = failed` and preserves the checkpoint. Rerunning the
same batch executes only missing/failed windows. A batch may resume only when
its source, converter, output schema, serialization, canonicalization,
splitter, role-router, smoke-test, and embedding fingerprints equal the
recorded values.

## 7. Stable IDs and Field Mapping

`job_id` is:

`linkedin-ml:` followed by the full SHA-256 hex digest of the canonical
JSON array `[company, title, location, canonical_jd]` serialized as UTF-8 RFC
8785 JCS.

The same canonical digest is stored as `source_record_hash`. A second digest of
the compact canonical JSON array `[company, title, canonical_jd]` is stored as
`posting_group_hash`.

Direct mappings are:

- `Co_Nm -> company`;
- `Job_Ttl -> title`;
- display `Job_Desc -> raw_jd`;
- `loc -> location`.

The remaining source columns are preserved in `source_metadata`, including
company employee/follower counts, work type, experience level, remote flag,
salary values, pay period, views, application type, and posting domain.
Pandas/CSV missing values and non-finite numbers become JSON `null`; JSON NaN
and Infinity are forbidden. Booleans and numbers remain typed values rather
than strings.

Derived fields use deterministic rules:

- `role_cluster` uses a versioned ordered rule table over the repository's
  allowed role taxonomy; title rules run first, JD rules second, first match
  wins, and `other` is the final fallback;
- `is_open = NULL`;
- `retrieval_eligible = FALSE` during trial and full staging;
- `freshness_status = 'snapshot_unverified'`;
- `deadline = NULL`;
- `visa_sponsor = NULL`;
- `min_years_exp = NULL` unless an unambiguous deterministic rule is later
  separately specified and tested;
- `degree_required = 'unknown'`;
- `responsibilities = NULL`;
- `required_skills = []`;
- `nice_to_have = []`.

The importer never turns missing evidence into a positive or negative fact.
The ordered role rule table is checked into the repository, independently
unit-tested, and fingerprinted in the input and import manifests.

## 8. Open/Unknown Retrieval Semantics

The public retrieval and RAPTOR filters change from `is_open = TRUE` to:

`retrieval_eligible = TRUE AND is_open IS DISTINCT FROM FALSE`

This includes only explicitly activated confirmed-open or unknown snapshot
records while excluding confirmed-closed and staging jobs. Trial and pre-cutover
validation use an internal validation entry point with an explicit batch-ID/job
ID allowlist and the physically separate staging chunk/node tables; they never
expose staging jobs or vectors through the public search path.
User-facing output must treat a NULL value as dataset-only/unverified and must
not display an Apply action or claim that the job is currently open.

## 9. Chunking and Embedding

The accepted 31,879 rows produce, with the current 1,800-character splitter:

- 31,879 metadata chunks;
- 88,369 raw-JD chunks;
- exactly 120,248 initial chunks; and
- an average of 3.77 chunks per job.

Because deterministic import leaves responsibilities and skill arrays empty,
the initial build contains metadata and raw-JD chunks only. Later enrichment
may add structured chunks in a separate, versioned job.

The count is tied to `linkedin_ml_canonical_v1` and the current
`chunking_1800_v1` implementation. Conversion writes the expected chunk count
to `input-manifest.json`; execution stops on a rule or splitter fingerprint
mismatch rather than silently accepting a new count.

Embedding requirements:

- model: `text-embedding-v4`;
- dimension: 1,024;
- pass `dimensions=settings.embed_dim` explicitly to the API;
- API batch size: at most 10 texts;
- bounded concurrent batches controlled by the existing embedding semaphore;
- bounded retries with recorded failures;
- no construction of tens of thousands of unbounded coroutines; and
- checkpoint commits by stable job-ID windows.

At batch size 10, the P0 design projects 12,025 chunk-embedding requests. The
optional full RAPTOR build adds at most 3,189 requests, giving a combined upper
bound of 15,214 build calls before small validation-query overhead. P0 and
optional RAPTOR have separate budgets and confirmation flags. A dry run must
report actual input characters, estimated tokens, request count, configured
rate limits, projected cost when pricing is configured, and database/storage
headroom before either full phase.

The full phase may start only when:

- the projected requests and tokens are within explicit configuration limits;
- the PostgreSQL data volume has at least 4 GiB free after a conservative
  estimate that includes production data, batch staging tables, both HNSW
  indexes, and cutover working headroom;
- the operator supplies the exact batch ID to the full-import confirmation
  flag; and
- the Qwen model/dimension smoke test succeeds.

Re-running a completed chunk window replaces the same stable chunk IDs and does
not increase counts. Existing embeddings are reused only when the chunk content
hash and embedding build fingerprint both match; otherwise that chunk is
re-embedded.

## 10. RAPTOR-lite Compatibility

The imported jobs are compatible with the existing RAPTOR-lite design after
their chunks exist. To preserve the P0 path required by `AGENTS.md`, the
100-job RAPTOR-lite mechanism test is an independent research gate, not a P0
cutover gate. Building all 31,890 expected nodes is an optional, post-cutover
P2 phase; neither can block jobs, BM25, dense retrieval, or P0 completion.

The builder must:

- ensure `raptor_nodes` and `raptor_node_chunks` exist;
- accept a `source_dataset` or explicit job-ID filter;
- add `source_dataset` and `build_version` provenance to RAPTOR nodes;
- build one job-summary node for each imported job;
- build at most one role-summary node for each of the 11 allowed role clusters;
- write job-to-chunk and role-to-chunk mappings;
- delete stale nodes and mappings for the same source dataset only during final
  reconciliation against a complete expected-node-ID manifest; and
- remain optional in ordinary P0 retrieval.

Node IDs are dataset-namespaced:

- job node: `job:{source_dataset}:{job_id}`;
- role node: `role:{source_dataset}:{role_cluster}`;
- job-node parent: `role:{source_dataset}:{role_cluster}`.

Trial nodes stay in the staging tables and never replace production nodes. The
optional full build uses the same new logical dataset namespace in staging and
publishes only after full reconciliation. Legacy nodes use the old dataset
namespace. Building or cleaning the new namespace therefore cannot overwrite
the old `role:<cluster>` rows or mappings before cutover. Existing legacy
unnamespaced nodes are treated as old-corpus rows and are deleted only in the
verified cleanup transaction.

The optional full builder is ordered:

1. Each succeeded job-ID window upserts only its job nodes and job-to-chunk
   mappings; it never performs dataset-wide cleanup.
2. After every job window succeeds, role summaries and role-to-chunk mappings
   are built once from the complete corpus.
3. Final reconciliation compares staging rows with the complete expected node
   and mapping manifests, performs one dataset-wide stale-row difference
   cleanup, and marks the build validated.
4. A short transaction copies the reconciled nodes/mappings to production and
   enables RAPTOR for the new dataset. Until then, public RAPTOR remains
   disabled and staging indexes are never queried publicly.

RAPTOR search must also prevent inactive staging role nodes from consuming the
public `node_k` budget. A public node query may return a role node only when an
`EXISTS` check finds at least one mapping from that node to the current
retrieval-eligible `allow_ids`. Internal trial validation additionally filters
by the exact new source dataset and trial job IDs.

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

`trial-manifest.json` stores the ordered 100 job IDs, cluster counts, selection
algorithm version, and SHA-256. A separate versioned
`retrieval-smoke-tests.json` stores fixed English queries, Chinese resume/query
texts, retrieval mode, Top-K, allowed trial IDs, expected role cluster, at
least one deterministic expected job ID where stable, minimum hit count, and
evidence-ownership assertions. These are mechanism fixtures, not a fabricated
relevance-label dataset. Trial jobs remain
`retrieval_eligible = FALSE`; validation queries are constrained to the exact
manifest job IDs.

P0 trial acceptance gates:

1. The archive is verified.
2. Exactly 100 source-tagged jobs exist for the trial batch.
3. All 100 remain hidden from the public search path.
4. A fixed old-corpus public query has identical candidate IDs before and after
   staging the trial through BM25 and dense retrieval.
5. Re-running the job import changes no row count or stable ID.
6. Every trial job has at least one metadata and one JD chunk.
7. Every embedding is finite and 1,024-dimensional.
8. There are no orphan chunks.
9. Every fixed English BM25/dense case satisfies its manifest hit-count,
   expected-ID/cluster, Top-K, and evidence-ownership assertions.
10. Every fixed Chinese-to-English dense case satisfies its manifest
    hit-count, expected-ID/cluster, Top-10, and evidence-ownership assertions.
11. A second P0 trial run produces identical counts and IDs.

Reaching `trial_p0_validated` allows the full P0 import to start regardless of
RAPTOR state. The independent 100-job RAPTOR research gates are:

1. the fixed legacy public RAPTOR candidate IDs are unchanged by trial staging;
2. one RAPTOR job node per trial job, non-empty role nodes, and no orphan
   mappings;
3. the fixed English RAPTOR case satisfies the manifest hit-count,
   expected-ID/cluster, Top-K, and evidence-ownership assertions;
4. the fixed Chinese RAPTOR case satisfies the same explicit assertions; and
5. a second RAPTOR trial build produces identical nodes and mappings.

A RAPTOR trial failure records `raptor_trial_failed` with its own error and
budget usage, but cannot change `trial_p0_validated`, stop full P0 import, or
block P0 cutover. The research branch may be repaired and rerun separately.

The already executed model-level smoke test is necessary but not sufficient:
`text-embedding-v4` returned three finite 1,024-dimensional vectors, and the
Chinese/English equivalent pair scored above the unrelated pair. Trial
P0 acceptance still requires real imported JD dense retrieval; RAPTOR research
acceptance separately requires real imported JD RAPTOR retrieval.

## 12. Full Import and Validation

The full import resumes the same logical source dataset after trial validation.
The 100 trial jobs are upserted as part of the 31,879 total; they are not added
on top. Every new job remains `retrieval_eligible = FALSE`, and all new chunks
remain in the physical staging tables, until the final cutover transaction.

Full P0 validation requires:

- exactly 31,879 new source-tagged jobs;
- exactly 31,879 distinct stable job IDs;
- zero new jobs visible through the public search path before cutover;
- fixed legacy public BM25 and dense candidate IDs remain identical to the
  pre-import baseline after all 31,879 jobs and 120,248 staging vectors exist;
- no rejected sentinel company names;
- no JD shorter than 300 normalized characters;
- no duplicate canonical job keys;
- exactly 120,248 initial chunks unless the checked-in splitter changes before
  execution, in which case the converter records and tests the new
  deterministic expected count;
- no orphan chunks;
- all embeddings finite and 1,024-dimensional;
- staging HNSW and GIN indexes present;
- the fixed English BM25/dense smoke manifest passes against staging;
- the fixed Chinese-to-English dense Top-10 smoke manifest passes against
  staging;
- retrieval evidence IDs resolve to the returned job's chunks;
- rerunning the full batch is idempotent; and
- the existing automated test suite passes.

The independent 100-job RAPTOR gates prove RAPTOR-lite compatibility. If the
optional full RAPTOR build is run, it separately requires one job node per
imported job, role-node and mapping reconciliation, finite 1,024-dimensional
vectors, fixed English and Chinese RAPTOR smoke manifests, an idempotent
rebuild, and zero public visibility until its own publish transaction.

These smoke tests do not replace Recall@K, Precision@K, MRR, or NDCG. Those
metrics remain unavailable for the new corpus until new relevance labels are
manually created.

Before the old active evaluation files are removed, code and tests that
hard-code `linkedin_postings_1000.csv`,
`offline_lexical_rankings_1000.json`, or the old relevance labels are migrated:

- unit tests use a small synthetic corpus under `tests/fixtures/`;
- corpus-integrity tests validate the new manifest and external canonical-file
  SHA-256 without committing the 124 MB source dataset;
- `generate_lexical_rankings.py` requires an explicit corpus/manifest path
  instead of defaulting to the removed 1,000-row file;
- the evaluation CLI exits with a clear
  `labels_pending_manual_annotation` error for the new corpus until labels
  exist; and
- metric algorithm tests continue to run against synthetic labels.

## 13. Cutover and Old-Corpus Cleanup

Cleanup begins only after every full P0 validation gate passes and the archive
is re-verified.

An early read-only dependency scan may report foreign keys and known JSON/text
references to old job IDs, but it is diagnostic only. The authoritative scan
runs after task fencing inside the cutover transaction.

Cutover follows the maintenance-mode state machine:

1. In a short transaction, take the exclusive corpus advisory lock, enter
   maintenance mode, and increment `corpus_epoch`. This waits for any state
   write already holding the shared lock. New task submissions are rejected;
   submitted/running tasks from the prior epoch are marked retryable
   `corpus_changed`, and any late writer is rejected by its epoch check.
2. Prepare and hash-check the complete new versioned corpus/evaluation bundle,
   including `labels_status = pending_manual_annotation`, without changing
   `active-corpus.json`.
3. Before the destructive transaction, compute the fixed smoke-query
   embeddings through Qwen, verify their model/dimension/build fingerprint, and
   hold the vectors as immutable cutover inputs. No external call is allowed
   inside the destructive transaction.
4. Run the database cutover transaction below, leaving maintenance mode set.
5. Atomically replace `active-corpus.json` with the new bundle pointer.
6. In a final short transaction, verify the supplied pointer SHA-256, active
   source, production counts, and `db_cutover_committed` phase; then set the
   batch/recovery phase to `cutover_complete` and leave maintenance mode.
7. Remove the superseded loose active files. A failure before step 6 leaves the
   service in maintenance and is resumed from the recorded recovery phase.

The database cutover transaction:

1. takes the exclusive corpus advisory lock;
2. verifies the exact old and new counts from the manifest and re-verifies the
   batch, epoch, maintenance, and eligibility state;
3. reruns the authoritative dependency scan under the fence. If any user
   feedback, case outcome, match history, session state, foreign key, or known
   JSON/text artifact references an old job, it rolls back without deleting or
   rewriting user state, records the exact dependency, and a short recovery
   transaction safely leaves maintenance mode on the still-legacy corpus;
4. deletes old `raptor_node_chunks` rows and old namespaced/legacy unnamespaced
   RAPTOR nodes;
5. deletes old production `job_chunks`;
6. copies exactly the reconciled 120,248 staging chunks into `job_chunks` with
   explicit columns and verifies their IDs and count;
7. sets all 31,879 new jobs to `retrieval_eligible = TRUE`;
8. sets the database-backed public RAPTOR feature state to disabled until an
   optional new full build is published;
9. sets old jobs to `retrieval_eligible = FALSE`;
10. calls a cutover-only `validate_public_snapshot(conn, query_vectors)` entry
   point serially on the same asyncpg connection. It reuses the public
   predicate and SQL builders but does not acquire from the pool or call
   `asyncio.gather`; it requires the intended HNSW plan, production evidence
   ownership, and no staging relation in the plan;
11. deletes old `jobs`;
12. deletes old import-batch metadata that is explicitly part of the archived
    corpus; and
13. while keeping maintenance mode set, writes
    `active_source_dataset = linkedin_jobs_ml_31879_v1`, the verified target
    pointer payload SHA-256, and
    `recovery_phase = db_cutover_committed`.

Production vector indexes see none of the staging vectors before this
transaction commits; concurrent readers retain their old MVCC snapshot until
commit, but the API is already in maintenance mode. The cutover uses lock and
statement timeouts and rolls back on any count, ID, timeout, plan,
query-fingerprint, or feature-state mismatch.

After the active pointer and final database activation both succeed:

- remove the five active `data/jobs/*_1000.csv` files;
- remove `data/jobs/linkedin_1000_manifest.txt`;
- remove the old active lexical ranking cache;
- remove the old corpus-bound relevance labels and manifest from active paths;
- retain or copy the query texts only as an unlabeled seed set under a new
  filename;
- create a new corpus manifest with `labels_status = pending_manual_annotation`;
  and
- recompute active file hashes.

Chunk staging rows are not dropped while any trial/full RAPTOR staging mapping
references them. After P0, the operator chooses one explicit branch:

- `raptor_published`: build/publish full RAPTOR, then delete mappings, nodes,
  and chunk staging in FK order; or
- `raptor_skipped`: first persist the verified 100-job RAPTOR report, then
  delete all RAPTOR mappings/nodes and chunk staging in FK order.

If full RAPTOR is requested after `raptor_skipped`, its resumable builder
recreates batch staging from production chunks before writing mappings.
Neither branch is on a public query path or a P0 completion gate.

The local `rollback.zip`, `input.zip`, and top-level manifest remain untouched.
Restoration uses `restore.ps1` and the archived manifests.

## 14. Error Handling and Safety

- Every destructive target is resolved to an explicit old job-ID list from the
  verified archive manifest.
- No destructive SQL uses a wildcard source name or an unresolved environment
  variable.
- Every external call uses the existing semaphore and a timeout.
- Every full external-call phase checks recorded request/token budgets and
  storage headroom before starting.
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
- exact old-corpus eligibility backfill;
- source-filtered chunk and RAPTOR builds;
- dataset-namespaced RAPTOR node IDs that cannot overwrite legacy role nodes;
- staging jobs remaining invisible to the public search path;
- staging vectors never entering a production query plan/index before cutover;
- atomic per-window writes, stale-chunk deletion, and contiguous checkpoints;
- splitter/converter/schema/serialization fingerprint invalidation;
- full RAPTOR job-window then role-summary build ordering;
- JSON-compatible `source_metadata` normalization;
- embedding-build fingerprint reuse and invalidation;
- request-budget and storage-headroom gates;
- atomic window lease/budget claims and stale-owner rejection;
- abort/supersede cleanup while preserving the audit ledger;
- the connection-aware serial cutover validation entry point;
- corpus-epoch checks on every job-ID-bearing state/result/feedback write;
- JCS stable-ID and pre-schema-journal hash vectors;
- replacement of old hard-coded evaluation paths with synthetic fixtures; and
- cleanup target resolution.

Integration tests cover:

- archive/export verification and full inverse cutover against the migrated
  schema in an isolated recovery database;
- unchanged legacy BM25/dense/RAPTOR candidates after schema migration, trial
  staging, and full staging;
- 100-job idempotent import;
- chunk and embedding reconciliation;
- RAPTOR mappings;
- English hybrid retrieval;
- Chinese-to-English dense/RAPTOR retrieval;
- full-count reconciliation; and
- cutover/cleanup rollback on dependency, timeout, feature-state, or count
  mismatch;
- crash recovery between maintenance, database cutover, active-pointer swap,
  and final service activation; and
- in-flight background-task fencing plus a dependency inserted immediately
  before attempted cutover;
- RAPTOR staging FK retention plus both publish/skip cleanup branches.

Live Qwen calls are limited to explicit integration commands. Normal unit tests
use deterministic test doubles and never consume API quota.

## 16. Completion Criteria

The P0 migration is complete only when:

- the verified archive and restoration instructions exist;
- both rollback and input ZIP packages reproduce their manifests;
- `ReactivateLegacy` has restored a simulated post-cutover state in an isolated
  database and reproduced the old public candidates and active file hashes;
- the 31,879-job corpus and 120,248 initial production chunks reconcile;
- all new jobs remain hidden until the cutover transaction;
- fixed English and Chinese P0 retrieval gates pass;
- a repeat import produces no duplicate rows;
- old database records and active files are removed only after validation;
- the final active source, corpus epoch, pointer payload hash, recovery phase,
  and maintenance state reconcile;
- the new manifest accurately states that freshness and labels are unknown;
- the final report reconciles projected versus actual embedding requests and
  confirms the model, explicit dimension, and build fingerprints;
- the test suite passes; and
- the final report lists actual counts, timings, failures, API calls, and any
  remaining limitations.

P0 migration completion does not require the optional full RAPTOR build. If it
is executed, its separate completion report must reconcile 31,879 job nodes,
at most 11 role nodes, mappings, embeddings, fixed English/Chinese RAPTOR
cases, publish state, and actual external-call usage. The smaller RAPTOR-lite
compatibility research deliverable is complete when the independent 100-job
English/Chinese gates pass and its immutable report is stored; failure or delay
does not revoke a completed P0 migration.
