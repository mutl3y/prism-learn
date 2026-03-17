#!/usr/bin/env python3
"""Materialize per-section rows from scan snapshots into a reduced SQL table.

This keeps learning.scan_snapshots.scan_payload as immutable raw data while
maintaining a query-friendly table: learning.scan_snapshot_sections.

Behavior:
- Creates required tables/indexes if they do not exist.
- Incrementally processes new snapshots by default.
- Applies persistent aliases from learning.section_title_aliases.
- Supports full refresh and alias re-application for existing rows.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any


def _require_psycopg():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for this script. Install it with `pip install psycopg[binary]`."
        ) from exc
    return psycopg


def _resolve_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = os.getenv("POSTGRES_USER", "learning_user")
    password = os.getenv("POSTGRES_PASSWORD", "learning_pass_change_me")
    db_name = os.getenv("POSTGRES_DB", "learning_scans")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _normalize_style_heading(heading: str) -> str:
    normalized = re.sub(r"[^a-z0-9()]+", " ", heading.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _ensure_objects(conn) -> None:
    ddl = """
    CREATE SCHEMA IF NOT EXISTS learning;

    CREATE TABLE IF NOT EXISTS learning.section_title_aliases (
        normalized_title TEXT PRIMARY KEY,
        section_id TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'manual_review',
        approved_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        CHECK (length(trim(normalized_title)) > 0),
        CHECK (length(trim(section_id)) > 0)
    );

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
    """
    with conn.cursor() as cur:
        cur.execute(ddl)


def _load_aliases(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT normalized_title, section_id FROM learning.section_title_aliases"
        )
        rows = cur.fetchall()
    return {str(n): str(sid) for n, sid in rows}


def _coerce_sections(raw_payload: Any) -> list[dict[str, Any]]:
    if isinstance(raw_payload, str):
        try:
            raw_payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            return []

    if not isinstance(raw_payload, dict):
        return []

    sections = (
        raw_payload.get("metadata", {}).get("style_guide", {}).get("sections", [])
    )
    if isinstance(sections, list):
        return [item for item in sections if isinstance(item, dict)]
    return []


def _get_start_snapshot_id(
    conn, full_refresh: bool, from_snapshot_id: int | None
) -> int:
    if from_snapshot_id is not None:
        return from_snapshot_id

    if full_refresh:
        return 0

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(snapshot_id), 0) FROM learning.scan_snapshot_sections"
        )
        value = cur.fetchone()[0]
    return int(value or 0)


def _fetch_snapshots(conn, start_snapshot_id: int, limit: int) -> list[tuple[Any, ...]]:
    sql = """
        SELECT
            s.id,
            s.target_type,
            s.target,
            s.captured_at_utc,
            s.batch_id,
            s.scan_payload
        FROM learning.scan_snapshots AS s
        WHERE s.id > %s
        ORDER BY s.id ASC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start_snapshot_id, limit))
        return cur.fetchall()


def _upsert_sections(
    conn, rows: list[tuple[Any, ...]], aliases: dict[str, str]
) -> tuple[int, int]:
    upserts = 0
    snapshots = 0

    sql = """
        INSERT INTO learning.scan_snapshot_sections (
            snapshot_id,
            section_index,
            target_type,
            target,
            captured_at_utc,
            batch_id,
            raw_section_id,
            effective_section_id,
            title,
            normalized_title,
            updated_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
        )
        ON CONFLICT (snapshot_id, section_index) DO UPDATE
        SET
            target_type = EXCLUDED.target_type,
            target = EXCLUDED.target,
            captured_at_utc = EXCLUDED.captured_at_utc,
            batch_id = EXCLUDED.batch_id,
            raw_section_id = EXCLUDED.raw_section_id,
            effective_section_id = EXCLUDED.effective_section_id,
            title = EXCLUDED.title,
            normalized_title = EXCLUDED.normalized_title,
            updated_at = NOW()
    """

    with conn.cursor() as cur:
        for (
            snapshot_id,
            target_type,
            target,
            captured_at_utc,
            batch_id,
            scan_payload,
        ) in rows:
            snapshots += 1
            sections = _coerce_sections(scan_payload)
            for section_index, section in enumerate(sections):
                raw_section_id = str(section.get("id") or "unknown")
                title = str(section.get("title") or "").strip()
                normalized_title = str(section.get("normalized_title") or "").strip()
                if not normalized_title and title:
                    normalized_title = _normalize_style_heading(title)
                if not normalized_title:
                    normalized_title = "unknown"

                effective_section_id = aliases.get(normalized_title, raw_section_id)

                cur.execute(
                    sql,
                    (
                        int(snapshot_id),
                        int(section_index),
                        str(target_type),
                        str(target),
                        captured_at_utc,
                        int(batch_id) if batch_id is not None else None,
                        raw_section_id,
                        effective_section_id,
                        title,
                        normalized_title,
                    ),
                )
                upserts += 1

    return snapshots, upserts


def _reapply_aliases(conn) -> int:
    sql = """
        UPDATE learning.scan_snapshot_sections AS s
        SET
            effective_section_id = COALESCE(a.section_id, s.raw_section_id),
            updated_at = NOW()
        FROM learning.section_title_aliases AS a
        WHERE a.normalized_title = s.normalized_title
          AND s.effective_section_id IS DISTINCT FROM COALESCE(a.section_id, s.raw_section_id)
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        return int(cur.rowcount or 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn", default=None, help="Postgres DSN (defaults to env-derived DSN)."
    )
    parser.add_argument(
        "--full-refresh",
        action="store_true",
        help="Truncate learning.scan_snapshot_sections before rebuilding.",
    )
    parser.add_argument(
        "--from-snapshot-id",
        type=int,
        default=None,
        help="Start processing strictly after this snapshot id.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="How many snapshots to read per batch (default: 1000).",
    )
    parser.add_argument(
        "--reapply-aliases",
        action="store_true",
        help="After ingest, recompute effective_section_id for existing rows using current aliases.",
    )
    args = parser.parse_args()

    if args.batch_size <= 0:
        print("error: --batch-size must be > 0", file=sys.stderr)
        return 1

    dsn = args.dsn or _resolve_dsn()

    try:
        psycopg = _require_psycopg()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    with psycopg.connect(dsn) as conn:
        conn.autocommit = False
        _ensure_objects(conn)

        if args.full_refresh:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE TABLE learning.scan_snapshot_sections")
            print("Truncated learning.scan_snapshot_sections", file=sys.stderr)

        aliases = _load_aliases(conn)
        print(f"Loaded {len(aliases)} aliases", file=sys.stderr)

        start_snapshot_id = _get_start_snapshot_id(
            conn,
            full_refresh=args.full_refresh,
            from_snapshot_id=args.from_snapshot_id,
        )
        print(f"Starting after snapshot id {start_snapshot_id}", file=sys.stderr)

        total_snapshots = 0
        total_upserts = 0

        while True:
            rows = _fetch_snapshots(conn, start_snapshot_id, args.batch_size)
            if not rows:
                break

            snapshots, upserts = _upsert_sections(conn, rows, aliases)
            conn.commit()

            total_snapshots += snapshots
            total_upserts += upserts
            start_snapshot_id = int(rows[-1][0])

            print(
                f"Processed snapshots={total_snapshots}, section_rows={total_upserts}, last_snapshot_id={start_snapshot_id}",
                file=sys.stderr,
            )

        reapplied = 0
        if args.reapply_aliases:
            reapplied = _reapply_aliases(conn)
            conn.commit()
            print(f"Reapplied aliases to {reapplied} rows", file=sys.stderr)

        print(
            f"Done. snapshots={total_snapshots}, section_rows={total_upserts}, alias_updates={reapplied}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
