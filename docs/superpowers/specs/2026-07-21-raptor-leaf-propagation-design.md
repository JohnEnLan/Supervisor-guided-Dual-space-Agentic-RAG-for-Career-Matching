# RAPTOR-lite Leaf Propagation and Job-level Fusion Design

## Goal

Replace direct summary-to-job score copying with an explicit
`raptor_node -> descendant job_chunk -> job_id` path, then fuse all retrieval
routes at `job_id` while exposing only original JD chunks as evidence.

## Root cause

The current code already converts RAPTOR hits to `job_id` before RRF, so the RRF
identifier universe is nominally consistent. However, role-summary similarity is
copied directly to several jobs and the summary node ID is used as evidence. This
skips leaf relevance, gives broad nodes uncontrolled fan-out, and violates the
desired original-evidence boundary.

## Storage

Add an optional P2 mapping table:

```text
raptor_node_chunks
  node_id
  chunk_id
  job_id
  depth
  leaf_rank
```

The offline RAPTOR builder rewrites mappings for every rebuilt node. Job-summary
nodes map to their own chunks at depth 1; role-summary nodes map to the chunks of
their source jobs at depth 2. The table is present in the schema snapshot, an
additive migration, and the runtime RAPTOR schema guard.

## Retrieval flow

1. SQL hard filtering produces allowed `job_id` values.
2. BM25, dense chunk retrieval, and optional RAPTOR node retrieval run in
   parallel.
3. RAPTOR fetches mapped original chunks for the retrieved nodes and scores each
   leaf against the same query embedding.
4. For each node, only the most relevant leaves are retained. Role nodes retain
   at most one leading leaf per job before the Top-N cap so one verbose job cannot
   consume the whole expansion.
5. Each propagated contribution applies:
   - depth decay (`1.0` for depth 1, `0.65` for each additional level);
   - fan-out normalization by the number of selected leaves;
   - query-to-leaf relevance.
6. Contributions that reach the same original chunk are combined, then chunks
   are aggregated to `job_id` for the RAPTOR ranking.
7. BM25, dense, and RAPTOR job rankings are fused by RRF at `job_id`.
8. Top jobs receive evidence payloads only from `job_chunks`; RAPTOR summary
   content is not published as JD evidence.

## Scoring

For a retrieved summary node `n` and selected descendant chunk `c`:

```text
contribution(n, c) =
  max(node_similarity, 0)
  * max(leaf_similarity, 0)
  * 0.65^(depth - 1)
  / selected_leaf_count(n)
```

The formula is used to order the optional RAPTOR route. RRF still consumes ranks,
not incompatible raw score scales.

## Compatibility and degradation

- RAPTOR remains disabled by default and cannot slow the P0 route.
- If no node-to-chunk mappings exist, the RAPTOR route contributes no candidates;
  BM25 and dense retrieval continue normally.
- Rebuilding the RAPTOR-lite index populates the new mapping table.
- No full recursive RAPTOR tree, knowledge graph, skill graph, or cross-encoder is
  introduced.

## Tests

- Schema and builder tests cover node-to-chunk mappings and depths.
- Pure propagation tests cover allowed-job filtering, depth decay, fan-out
  normalization, per-role job diversity, and the Top-N limit.
- Hybrid-search tests prove RRF receives `job_id` rankings and public evidence IDs
  come from original job chunks rather than summary nodes.

