"""Batch and freshness reporting helpers."""

from __future__ import annotations

from typing import Any

from .reporting_common import require_psycopg


def fetch_recent_batch_summary(dsn: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return recent batch-level success/failure metrics."""
    psycopg = require_psycopg()

    sql = """
        SELECT
            b.id,
            b.run_label,
            b.target_type,
            b.total_targets,
            b.succeeded_targets,
            b.failed_targets,
            ROUND(
                CASE
                    WHEN b.total_targets = 0 THEN 0
                    ELSE (b.failed_targets::numeric / b.total_targets::numeric) * 100
                END,
                2
            ) AS failure_rate_pct,
            b.started_at_utc,
            b.finished_at_utc
        FROM learning.scan_batches AS b
        ORDER BY b.started_at_utc DESC
        LIMIT %s
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()

    keys = [
        "id",
        "run_label",
        "target_type",
        "total_targets",
        "succeeded_targets",
        "failed_targets",
        "failure_rate_pct",
        "started_at_utc",
        "finished_at_utc",
    ]
    return [dict(zip(keys, row, strict=False)) for row in rows]


def fetch_recent_failures(dsn: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return recent failure records for quick troubleshooting."""
    psycopg = require_psycopg()

    sql = """
        SELECT
            f.id,
            f.target_type,
            f.target,
            f.error_type,
            f.error_message,
            f.captured_at_utc,
            f.batch_id
        FROM learning.scan_failures AS f
        ORDER BY f.captured_at_utc DESC
        LIMIT %s
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()

    keys = [
        "id",
        "target_type",
        "target",
        "error_type",
        "error_message",
        "captured_at_utc",
        "batch_id",
    ]
    return [dict(zip(keys, row, strict=False)) for row in rows]


def fetch_fresh_targets(
    dsn: str,
    *,
    target_type: str,
    targets: list[str],
    max_age_days: int,
) -> list[dict[str, Any]]:
    """Return latest persisted snapshots that are newer than the freshness window."""
    if max_age_days <= 0 or not targets:
        return []

    psycopg = require_psycopg()

    sql = """
        WITH ranked AS (
            SELECT
                s.target,
                s.captured_at_utc,
                s.batch_id,
                b.run_label,
                ROW_NUMBER() OVER (
                    PARTITION BY s.target
                    ORDER BY s.captured_at_utc DESC, s.id DESC
                ) AS rn
            FROM learning.scan_snapshots AS s
            LEFT JOIN learning.scan_batches AS b ON b.id = s.batch_id
            WHERE s.target_type = %s
              AND s.target = ANY(%s)
        )
        SELECT
            ranked.target,
            ranked.captured_at_utc,
            ranked.batch_id,
            ranked.run_label
        FROM ranked
        WHERE ranked.rn = 1
          AND ranked.captured_at_utc >= NOW() - (%s * INTERVAL '1 day')
        ORDER BY ranked.captured_at_utc DESC, ranked.target ASC
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (target_type, targets, max_age_days))
            rows = cur.fetchall()

    keys = ["target", "captured_at_utc", "batch_id", "run_label"]
    return [dict(zip(keys, row, strict=False)) for row in rows]
