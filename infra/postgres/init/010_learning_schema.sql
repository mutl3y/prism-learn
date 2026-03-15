-- Learning-loop operational schema.
-- Designed to match learning_app_scaffold payload envelopes while preserving
-- full scanner payload fidelity in JSONB.

CREATE SCHEMA IF NOT EXISTS learning;

CREATE TABLE IF NOT EXISTS learning.scan_batches (
    id BIGSERIAL PRIMARY KEY,
    batch_uid UUID NOT NULL DEFAULT gen_random_uuid(),
    schema_version INTEGER NOT NULL DEFAULT 1,
    target_type TEXT NOT NULL CHECK (target_type IN ('role_path', 'repo_url')),
    run_label TEXT,
    total_targets INTEGER NOT NULL DEFAULT 0 CHECK (total_targets >= 0),
    succeeded_targets INTEGER NOT NULL DEFAULT 0 CHECK (succeeded_targets >= 0),
    failed_targets INTEGER NOT NULL DEFAULT 0 CHECK (failed_targets >= 0),
    started_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at_utc TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (batch_uid)
);

CREATE TABLE IF NOT EXISTS learning.scan_snapshots (
    id BIGSERIAL PRIMARY KEY,
    snapshot_uid UUID NOT NULL DEFAULT gen_random_uuid(),
    schema_version INTEGER NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('role_path', 'repo_url')),
    target TEXT NOT NULL,
    captured_at_utc TIMESTAMPTZ NOT NULL,
    batch_id BIGINT REFERENCES learning.scan_batches(id) ON DELETE SET NULL,
    scan_payload JSONB NOT NULL,
    role_name TEXT GENERATED ALWAYS AS (COALESCE(scan_payload ->> 'role_name', '')) STORED,
    scanner_counters JSONB GENERATED ALWAYS AS (COALESCE(scan_payload #> '{metadata,scanner_counters}', '{}'::jsonb)) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snapshot_uid)
);

CREATE TABLE IF NOT EXISTS learning.scan_failures (
    id BIGSERIAL PRIMARY KEY,
    failure_uid UUID NOT NULL DEFAULT gen_random_uuid(),
    schema_version INTEGER NOT NULL,
    target_type TEXT NOT NULL CHECK (target_type IN ('role_path', 'repo_url')),
    target TEXT NOT NULL,
    captured_at_utc TIMESTAMPTZ NOT NULL,
    batch_id BIGINT REFERENCES learning.scan_batches(id) ON DELETE SET NULL,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    error_context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (failure_uid)
);

CREATE INDEX IF NOT EXISTS idx_scan_batches_started_at
    ON learning.scan_batches (started_at_utc DESC);

CREATE INDEX IF NOT EXISTS idx_scan_snapshots_captured_at
    ON learning.scan_snapshots (captured_at_utc DESC);

CREATE INDEX IF NOT EXISTS idx_scan_snapshots_target
    ON learning.scan_snapshots (target_type, target, captured_at_utc DESC);

CREATE INDEX IF NOT EXISTS idx_scan_snapshots_role_name
    ON learning.scan_snapshots (role_name);

CREATE INDEX IF NOT EXISTS idx_scan_snapshots_payload_gin
    ON learning.scan_snapshots USING GIN (scan_payload);

CREATE INDEX IF NOT EXISTS idx_scan_failures_captured_at
    ON learning.scan_failures (captured_at_utc DESC);

CREATE INDEX IF NOT EXISTS idx_scan_failures_target
    ON learning.scan_failures (target_type, target, captured_at_utc DESC);

CREATE VIEW learning.latest_snapshot_per_target AS
SELECT DISTINCT ON (s.target_type, s.target)
    s.id,
    s.snapshot_uid,
    s.schema_version,
    s.target_type,
    s.target,
    s.captured_at_utc,
    s.batch_id,
    s.role_name,
    s.scanner_counters,
    s.scan_payload
FROM learning.scan_snapshots AS s
ORDER BY s.target_type, s.target, s.captured_at_utc DESC;
