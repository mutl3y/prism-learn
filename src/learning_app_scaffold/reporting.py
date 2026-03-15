"""Query helpers for learning-loop operational visibility."""

from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any


def _require_psycopg():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for reporting helpers. Install it with `pip install psycopg[binary]`."
        ) from exc
    return psycopg


def _coerce_json_document(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        loaded = json.loads(value)
        if isinstance(loaded, dict):
            return loaded
    return {}


def _normalize_style_heading(heading: str) -> str:
    normalized = re.sub(r"[^a-z0-9()]+", " ", heading.lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _build_section_title_stats_from_sections(sections: Any) -> dict[str, Any]:
    if not isinstance(sections, list):
        return {}

    by_section_id: dict[str, dict[str, Any]] = {}
    for raw_section in sections:
        if not isinstance(raw_section, dict):
            continue
        section_id = str(raw_section.get("id") or "unknown")
        title = str(raw_section.get("title") or "").strip()
        normalized_title = str(raw_section.get("normalized_title") or "").strip()
        if not normalized_title and title:
            normalized_title = _normalize_style_heading(title)

        bucket = by_section_id.setdefault(
            section_id,
            {
                "count": 0,
                "known": section_id != "unknown",
                "titles": [],
                "normalized_titles": [],
            },
        )
        bucket["count"] = int(bucket["count"]) + 1
        if title and title not in bucket["titles"]:
            bucket["titles"].append(title)
        if normalized_title and normalized_title not in bucket["normalized_titles"]:
            bucket["normalized_titles"].append(normalized_title)

    if not by_section_id:
        return {}

    known_sections = sum(
        int(bucket["count"])
        for section_id, bucket in by_section_id.items()
        if section_id != "unknown"
    )
    unknown_sections = int(by_section_id.get("unknown", {}).get("count", 0))
    total_sections = sum(int(bucket["count"]) for bucket in by_section_id.values())

    return {
        "total_sections": total_sections,
        "known_sections": known_sections,
        "unknown_sections": unknown_sections,
        "by_section_id": by_section_id,
    }


def fetch_recent_batch_summary(dsn: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return recent batch-level success/failure metrics."""
    psycopg = _require_psycopg()

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
    psycopg = _require_psycopg()

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

    psycopg = _require_psycopg()

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


def fetch_section_title_report(
    dsn: str,
    *,
    batch_id: int | None = None,
    run_label: str | None = None,
    latest_per_target: bool = True,
) -> dict[str, Any]:
    """Aggregate persisted style-guide section-title observations."""
    psycopg = _require_psycopg()

    filters: list[str] = [
        "("
        "s.scan_payload->'metadata'->'style_guide'->'section_title_stats' IS NOT NULL "
        "OR s.scan_payload->'metadata'->'style_guide'->'sections' IS NOT NULL"
        ")"
    ]
    params: list[Any] = []

    if batch_id is not None:
        filters.append("s.batch_id = %s")
        params.append(batch_id)

    if run_label is not None:
        filters.append("b.run_label = %s")
        params.append(run_label)

    where_clause = " AND ".join(filters)
    ranking_clause = "WHERE ranked.rn = 1" if latest_per_target else ""
    sql = f"""
        WITH ranked AS (
            SELECT
                s.target,
                s.batch_id,
                s.captured_at_utc,
                s.scan_payload->'metadata'->'style_guide'->'section_title_stats' AS section_title_stats,
                s.scan_payload->'metadata'->'style_guide'->'sections' AS style_sections,
                ROW_NUMBER() OVER (
                    PARTITION BY s.target
                    ORDER BY s.captured_at_utc DESC, s.id DESC
                ) AS rn
            FROM learning.scan_snapshots AS s
            LEFT JOIN learning.scan_batches AS b ON b.id = s.batch_id
            WHERE {where_clause}
        )
        SELECT
            ranked.target,
            ranked.batch_id,
            ranked.captured_at_utc,
            ranked.section_title_stats,
            ranked.style_sections
        FROM ranked
        {ranking_clause}
        ORDER BY ranked.captured_at_utc DESC, ranked.target ASC
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    section_buckets: dict[str, dict[str, Any]] = {}
    unknown_title_buckets: dict[str, dict[str, Any]] = {}
    distinct_targets: set[str] = set()
    total_sections = 0
    known_sections = 0
    unknown_sections = 0

    for target, row_batch_id, captured_at_utc, raw_stats, raw_sections in rows:
        stats = _coerce_json_document(raw_stats)
        if not stats:
            if isinstance(raw_sections, str):
                raw_sections = json.loads(raw_sections)
            stats = _build_section_title_stats_from_sections(raw_sections)
        if not stats:
            continue

        distinct_targets.add(str(target))
        total_sections += int(stats.get("total_sections") or 0)
        known_sections += int(stats.get("known_sections") or 0)
        unknown_sections += int(stats.get("unknown_sections") or 0)

        by_section_id = stats.get("by_section_id") or {}
        for section_id, raw_bucket in by_section_id.items():
            bucket = raw_bucket if isinstance(raw_bucket, dict) else {}
            aggregate = section_buckets.setdefault(
                str(section_id),
                {
                    "section_id": str(section_id),
                    "known": str(section_id) != "unknown",
                    "count": 0,
                    "snapshot_count": 0,
                    "targets": set(),
                    "title_counts": Counter(),
                    "normalized_title_counts": Counter(),
                },
            )
            aggregate["count"] = int(aggregate["count"]) + int(bucket.get("count") or 0)
            aggregate["snapshot_count"] = int(aggregate["snapshot_count"]) + 1
            aggregate["targets"].add(str(target))

            titles = [
                str(value).strip()
                for value in bucket.get("titles") or []
                if str(value).strip()
            ]
            normalized_titles = [
                str(value).strip()
                for value in bucket.get("normalized_titles") or []
                if str(value).strip()
            ]

            for title in titles:
                aggregate["title_counts"][title] += 1
            for normalized_title in normalized_titles:
                aggregate["normalized_title_counts"][normalized_title] += 1

            if str(section_id) != "unknown":
                continue

            for index, normalized_title in enumerate(normalized_titles):
                unknown_bucket = unknown_title_buckets.setdefault(
                    normalized_title,
                    {
                        "normalized_title": normalized_title,
                        "count": 0,
                        "titles": Counter(),
                        "targets": set(),
                        "batch_ids": set(),
                        "latest_seen_at": captured_at_utc,
                    },
                )
                unknown_bucket["count"] = int(unknown_bucket["count"]) + 1
                unknown_bucket["targets"].add(str(target))
                if row_batch_id is not None:
                    unknown_bucket["batch_ids"].add(int(row_batch_id))
                title = titles[index] if index < len(titles) else normalized_title
                unknown_bucket["titles"][title] += 1
                if str(captured_at_utc) > str(unknown_bucket["latest_seen_at"]):
                    unknown_bucket["latest_seen_at"] = captured_at_utc

    sections = []
    for aggregate in section_buckets.values():
        sections.append(
            {
                "section_id": aggregate["section_id"],
                "known": aggregate["known"],
                "count": aggregate["count"],
                "snapshot_count": aggregate["snapshot_count"],
                "distinct_targets": len(aggregate["targets"]),
                "sample_targets": sorted(aggregate["targets"])[:5],
                "titles": [
                    {"title": title, "count": count}
                    for title, count in aggregate["title_counts"].most_common()
                ],
                "normalized_titles": [
                    {"title": title, "count": count}
                    for title, count in aggregate[
                        "normalized_title_counts"
                    ].most_common()
                ],
            }
        )

    unknown_titles = []
    for aggregate in unknown_title_buckets.values():
        unknown_titles.append(
            {
                "normalized_title": aggregate["normalized_title"],
                "count": aggregate["count"],
                "distinct_targets": len(aggregate["targets"]),
                "sample_targets": sorted(aggregate["targets"])[:5],
                "batch_ids": sorted(aggregate["batch_ids"]),
                "latest_seen_at": aggregate["latest_seen_at"],
                "titles": [
                    {"title": title, "count": count}
                    for title, count in aggregate["titles"].most_common()
                ],
            }
        )

    sections.sort(key=lambda item: (-int(item["count"]), str(item["section_id"])))
    unknown_titles.sort(
        key=lambda item: (-int(item["count"]), str(item["normalized_title"]))
    )

    return {
        "selection": {
            "batch_id": batch_id,
            "run_label": run_label,
            "latest_per_target": latest_per_target,
        },
        "snapshot_count": len(rows),
        "distinct_targets": len(distinct_targets),
        "total_sections": total_sections,
        "known_sections": known_sections,
        "unknown_sections": unknown_sections,
        "sections": sections,
        "unknown_titles": unknown_titles,
    }
