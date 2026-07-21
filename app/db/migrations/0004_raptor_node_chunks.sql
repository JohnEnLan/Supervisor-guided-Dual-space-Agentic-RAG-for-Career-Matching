-- Optional RAPTOR-lite lineage from summary nodes to original JD chunks.
CREATE TABLE IF NOT EXISTS raptor_node_chunks (
    node_id   TEXT NOT NULL REFERENCES raptor_nodes(node_id) ON DELETE CASCADE,
    chunk_id  TEXT NOT NULL REFERENCES job_chunks(chunk_id) ON DELETE CASCADE,
    job_id    TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
    depth     SMALLINT NOT NULL CHECK (depth >= 1),
    leaf_rank INTEGER NOT NULL CHECK (leaf_rank >= 1),
    PRIMARY KEY (node_id, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_raptor_node_chunks_job
    ON raptor_node_chunks (job_id, node_id);
