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

-- Human-readable display titles for known section IDs.
-- section_id stays as the stable internal key; display_title is what appears in reports.
-- Update freely without touching any other table.
CREATE TABLE IF NOT EXISTS learning.section_display_titles (
    section_id TEXT PRIMARY KEY,
    display_title TEXT NOT NULL,
    updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (length(trim(section_id)) > 0),
    CHECK (length(trim(display_title)) > 0)
);

-- Approved normalized-title aliases for persistent reduction of unknown section labels.
CREATE TABLE IF NOT EXISTS learning.section_title_aliases (
    normalized_title TEXT PRIMARY KEY,
    section_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual_review',
    approved_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (length(trim(normalized_title)) > 0),
    CHECK (length(trim(section_id)) > 0)
);

-- Derived per-section rows materialized from scan_snapshots.scan_payload.
-- Keeps raw JSON immutable while supporting fast aggregate queries.
CREATE TABLE IF NOT EXISTS learning.scan_snapshot_sections (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id BIGINT NOT NULL REFERENCES learning.scan_snapshots(id) ON DELETE CASCADE,
    section_index INTEGER NOT NULL,
    target_type TEXT NOT NULL,
    target TEXT NOT NULL,
    captured_at_utc TIMESTAMPTZ NOT NULL,
    batch_id BIGINT,
    raw_section_id TEXT NOT NULL,
    effective_section_id TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snapshot_id, section_index)
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

CREATE INDEX IF NOT EXISTS idx_section_aliases_section_id
    ON learning.section_title_aliases (section_id);

CREATE INDEX IF NOT EXISTS idx_snapshot_sections_snapshot
    ON learning.scan_snapshot_sections (snapshot_id);

CREATE INDEX IF NOT EXISTS idx_snapshot_sections_effective_section
    ON learning.scan_snapshot_sections (effective_section_id);

CREATE INDEX IF NOT EXISTS idx_snapshot_sections_normalized_title
    ON learning.scan_snapshot_sections (normalized_title);

CREATE INDEX IF NOT EXISTS idx_snapshot_sections_target
    ON learning.scan_snapshot_sections (target_type, target, captured_at_utc DESC);

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
