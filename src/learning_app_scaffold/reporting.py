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


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_doc_quality_metrics(payload: Any) -> dict[str, Any]:
    document = _coerce_json_document(payload)
    metadata = document.get("metadata") if isinstance(document, dict) else {}
    counters = metadata.get("scanner_counters") if isinstance(metadata, dict) else {}
    counters = counters if isinstance(counters, dict) else {}

    total_variables = _coerce_int(counters.get("total_variables"))
    unresolved_variables = _coerce_int(counters.get("unresolved_variables"))
    ambiguous_variables = _coerce_int(counters.get("ambiguous_variables"))

    high_confidence = _coerce_int(counters.get("high_confidence_variables"))
    medium_confidence = _coerce_int(counters.get("medium_confidence_variables"))
    low_confidence = _coerce_int(counters.get("low_confidence_variables"))
    confidence_total = high_confidence + medium_confidence + low_confidence

    confidence_avg = None
    if confidence_total > 0:
        confidence_avg = round(
            (
                (high_confidence * 0.95)
                + (medium_confidence * 0.80)
                + (low_confidence * 0.50)
            )
            / float(confidence_total),
            4,
        )

    resolved_variables = max(0, total_variables - unresolved_variables)
    return {
        "variable_count": total_variables,
        "resolved_count": resolved_variables,
        "unresolved_count": unresolved_variables,
        "ambiguity_count": ambiguous_variables,
        "confidence_avg": confidence_avg,
    }


def _build_doc_quality_delta(
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if not previous:
        return {
            "variable_count_delta": None,
            "resolved_count_delta": None,
            "unresolved_count_delta": None,
            "ambiguity_count_delta": None,
            "confidence_avg_delta": None,
        }

    previous_confidence = previous.get("confidence_avg")
    current_confidence = current.get("confidence_avg")

    confidence_delta = None
    if isinstance(previous_confidence, (float, int)) and isinstance(
        current_confidence, (float, int)
    ):
        confidence_delta = round(
            float(current_confidence) - float(previous_confidence), 4
        )

    return {
        "variable_count_delta": int(current["variable_count"])
        - int(previous["variable_count"]),
        "resolved_count_delta": int(current["resolved_count"])
        - int(previous["resolved_count"]),
        "unresolved_count_delta": int(current["unresolved_count"])
        - int(previous["unresolved_count"]),
        "ambiguity_count_delta": int(current["ambiguity_count"])
        - int(previous["ambiguity_count"]),
        "confidence_avg_delta": confidence_delta,
    }


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
    source: str = "raw",
) -> dict[str, Any]:
    """Aggregate persisted style-guide section-title observations."""
    psycopg = _require_psycopg()

    if source not in {"raw", "reduced"}:
        raise ValueError("source must be one of: raw, reduced")

    if source == "reduced":
        filters: list[str] = ["1=1"]
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
            WITH candidate_snapshots AS (
                SELECT DISTINCT
                    s.snapshot_id,
                    s.target,
                    s.batch_id,
                    s.captured_at_utc
                FROM learning.scan_snapshot_sections AS s
                LEFT JOIN learning.scan_batches AS b ON b.id = s.batch_id
                WHERE {where_clause}
            ),
            ranked AS (
                SELECT
                    snapshot_id,
                    target,
                    batch_id,
                    captured_at_utc,
                    ROW_NUMBER() OVER (
                        PARTITION BY target
                        ORDER BY captured_at_utc DESC, snapshot_id DESC
                    ) AS rn
                FROM candidate_snapshots
            ),
            selected_snapshots AS (
                SELECT
                    snapshot_id,
                    target,
                    batch_id,
                    captured_at_utc
                FROM ranked
                {ranking_clause}
            )
            SELECT
                sec.snapshot_id,
                sec.target,
                sec.batch_id,
                sec.captured_at_utc,
                sec.effective_section_id,
                sec.title,
                sec.normalized_title
            FROM learning.scan_snapshot_sections AS sec
            JOIN selected_snapshots AS ss ON ss.snapshot_id = sec.snapshot_id
            ORDER BY sec.captured_at_utc DESC, sec.target ASC, sec.snapshot_id ASC, sec.section_index ASC
        """

        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute(sql, tuple(params))
                except Exception as exc:
                    if "scan_snapshot_sections" in str(exc):
                        raise RuntimeError(
                            "Reduced source requested but learning.scan_snapshot_sections is unavailable. "
                            "Run scripts/learning_materialize_sections.py first."
                        ) from exc
                    raise
                rows = cur.fetchall()

                # Fetch display titles (best-effort; table may not exist yet)
                display_titles: dict[str, str] = {}
                try:
                    cur.execute(
                        "SELECT section_id, display_title FROM learning.section_display_titles"
                    )
                    display_titles = {r[0]: r[1] for r in cur.fetchall()}
                except Exception:
                    pass

        section_buckets: dict[str, dict[str, Any]] = {}
        unknown_title_buckets: dict[str, dict[str, Any]] = {}
        distinct_targets: set[str] = set()
        distinct_snapshots: set[int] = set()
        total_sections = 0
        known_sections = 0
        unknown_sections = 0

        for (
            snapshot_id,
            target,
            row_batch_id,
            captured_at_utc,
            section_id,
            title,
            normalized_title,
        ) in rows:
            sid = str(section_id or "unknown")
            heading = (
                str(title or "").strip() or str(normalized_title or "").strip() or sid
            )
            normalized = str(
                normalized_title or ""
            ).strip() or _normalize_style_heading(heading)

            distinct_targets.add(str(target))
            distinct_snapshots.add(int(snapshot_id))
            total_sections += 1
            if sid == "unknown":
                unknown_sections += 1
            else:
                known_sections += 1

            aggregate = section_buckets.setdefault(
                sid,
                {
                    "section_id": sid,
                    "known": sid != "unknown",
                    "count": 0,
                    "snapshot_count": 0,
                    "targets": set(),
                    "title_counts": Counter(),
                    "normalized_title_counts": Counter(),
                    "seen_snapshots": set(),
                },
            )
            aggregate["count"] = int(aggregate["count"]) + 1
            aggregate["targets"].add(str(target))
            aggregate["title_counts"][heading] += 1
            aggregate["normalized_title_counts"][normalized] += 1
            if int(snapshot_id) not in aggregate["seen_snapshots"]:
                aggregate["snapshot_count"] = int(aggregate["snapshot_count"]) + 1
                aggregate["seen_snapshots"].add(int(snapshot_id))

            if sid != "unknown":
                continue

            unknown_bucket = unknown_title_buckets.setdefault(
                normalized,
                {
                    "normalized_title": normalized,
                    "count": 0,
                    "titles": Counter(),
                    "targets": set(),
                    "batch_ids": set(),
                    "latest_seen_at": captured_at_utc,
                    "seen_snapshots": set(),
                },
            )
            unknown_bucket["titles"][heading] += 1
            unknown_bucket["targets"].add(str(target))
            if row_batch_id is not None:
                unknown_bucket["batch_ids"].add(int(row_batch_id))
            if str(captured_at_utc) > str(unknown_bucket["latest_seen_at"]):
                unknown_bucket["latest_seen_at"] = captured_at_utc
            if int(snapshot_id) not in unknown_bucket["seen_snapshots"]:
                unknown_bucket["count"] = int(unknown_bucket["count"]) + 1
                unknown_bucket["seen_snapshots"].add(int(snapshot_id))

        sections = []
        for aggregate in section_buckets.values():
            sid = aggregate["section_id"]
            sections.append(
                {
                    "section_id": sid,
                    "display_title": display_titles.get(sid),
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
                "source": source,
            },
            "snapshot_count": len(distinct_snapshots),
            "distinct_targets": len(distinct_targets),
            "total_sections": total_sections,
            "known_sections": known_sections,
            "unknown_sections": unknown_sections,
            "sections": sections,
            "unknown_titles": unknown_titles,
        }

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
            "source": source,
        },
        "snapshot_count": len(rows),
        "distinct_targets": len(distinct_targets),
        "total_sections": total_sections,
        "known_sections": known_sections,
        "unknown_sections": unknown_sections,
        "sections": sections,
        "unknown_titles": unknown_titles,
    }


def fetch_doc_quality_report(
    dsn: str,
    *,
    batch_id: int | None = None,
    run_label: str | None = None,
) -> dict[str, Any]:
    """Return before/after document quality metrics from persisted snapshots.

    Uses the latest and previous snapshot per target so callers can track deltas
    in variable coverage, ambiguity, and confidence over time.
    """
    psycopg = _require_psycopg()

    filters: list[str] = [
        "(s.scan_payload->'metadata'->'scanner_counters') IS NOT NULL",
    ]
    params: list[Any] = []

    if batch_id is not None:
        filters.append("s.batch_id = %s")
        params.append(batch_id)

    if run_label is not None:
        filters.append("b.run_label = %s")
        params.append(run_label)

    where_clause = " AND ".join(filters)
    sql = f"""
        WITH ranked AS (
            SELECT
                s.id,
                s.target,
                s.batch_id,
                s.captured_at_utc,
                s.scan_payload,
                ROW_NUMBER() OVER (
                    PARTITION BY s.target
                    ORDER BY s.captured_at_utc DESC, s.id DESC
                ) AS rn
            FROM learning.scan_snapshots AS s
            LEFT JOIN learning.scan_batches AS b ON b.id = s.batch_id
            WHERE {where_clause}
        )
        SELECT
            latest.target,
            latest.batch_id,
            latest.captured_at_utc,
            latest.scan_payload,
            previous.captured_at_utc,
            previous.scan_payload
        FROM ranked AS latest
        LEFT JOIN ranked AS previous
          ON previous.target = latest.target
         AND previous.rn = 2
        WHERE latest.rn = 1
        ORDER BY latest.captured_at_utc DESC, latest.target ASC
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    targets: list[dict[str, Any]] = []
    improved = 0
    regressed = 0
    stable = 0

    for (
        target,
        row_batch_id,
        captured_at_utc,
        current_payload,
        previous_captured_at_utc,
        previous_payload,
    ) in rows:
        current_metrics = _extract_doc_quality_metrics(current_payload)
        previous_metrics = (
            _extract_doc_quality_metrics(previous_payload)
            if previous_payload is not None
            else None
        )
        delta = _build_doc_quality_delta(current_metrics, previous_metrics)

        resolved_delta = delta["resolved_count_delta"]
        ambiguity_delta = delta["ambiguity_count_delta"]
        confidence_delta = delta["confidence_avg_delta"]

        trend = "baseline"
        if previous_metrics is not None:
            if (
                (resolved_delta or 0) > 0
                or (ambiguity_delta or 0) < 0
                or (confidence_delta or 0) > 0
            ):
                trend = "improved"
                improved += 1
            elif (
                (resolved_delta or 0) < 0
                or (ambiguity_delta or 0) > 0
                or (confidence_delta or 0) < 0
            ):
                trend = "regressed"
                regressed += 1
            else:
                trend = "stable"
                stable += 1

        targets.append(
            {
                "target": str(target),
                "batch_id": int(row_batch_id) if row_batch_id is not None else None,
                "captured_at_utc": captured_at_utc,
                "previous_captured_at_utc": previous_captured_at_utc,
                "current": current_metrics,
                "previous": previous_metrics,
                "delta": delta,
                "trend": trend,
            }
        )

    return {
        "selection": {
            "batch_id": batch_id,
            "run_label": run_label,
            "latest_per_target": True,
        },
        "target_count": len(targets),
        "targets_with_previous": sum(
            1 for item in targets if item["previous"] is not None
        ),
        "trend_counts": {
            "improved": improved,
            "regressed": regressed,
            "stable": stable,
            "baseline": sum(1 for item in targets if item["previous"] is None),
        },
        "targets": targets,
    }


def submit_section_feedback(
    dsn: str,
    *,
    target: str,
    section_id: str,
    section_quality: int,
    title_helpfulness: int,
    content_accuracy: int,
    notes: str | None = None,
    source: str = "manual_review",
) -> None:
    """Persist a section-level feedback signal for future ranking/tuning."""
    psycopg = _require_psycopg()

    sql = """
        INSERT INTO learning.section_feedback (
            target,
            section_id,
            section_quality,
            title_helpfulness,
            content_accuracy,
            notes,
            source
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    target,
                    section_id,
                    int(section_quality),
                    int(title_helpfulness),
                    int(content_accuracy),
                    notes,
                    source,
                ),
            )
        conn.commit()


def fetch_section_feedback_ranking(
    dsn: str,
    *,
    min_feedback: int = 1,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Aggregate feedback scores by section for ranking/tuning workflows."""
    psycopg = _require_psycopg()

    sql = """
        SELECT
            section_id,
            COUNT(*) AS feedback_count,
            ROUND(AVG(section_quality::numeric), 3) AS avg_section_quality,
            ROUND(AVG(title_helpfulness::numeric), 3) AS avg_title_helpfulness,
            ROUND(AVG(content_accuracy::numeric), 3) AS avg_content_accuracy,
            ROUND(
                AVG(
                    (
                        section_quality::numeric
                        + title_helpfulness::numeric
                        + content_accuracy::numeric
                    ) / 3.0
                ),
                3
            ) AS avg_feedback_score,
            MAX(captured_at_utc) AS latest_feedback_at
        FROM learning.section_feedback
        GROUP BY section_id
        HAVING COUNT(*) >= %s
        ORDER BY avg_feedback_score DESC, feedback_count DESC, section_id ASC
        LIMIT %s
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (min_feedback, limit))
            rows = cur.fetchall()

    keys = [
        "section_id",
        "feedback_count",
        "avg_section_quality",
        "avg_title_helpfulness",
        "avg_content_accuracy",
        "avg_feedback_score",
        "latest_feedback_at",
    ]
    return [dict(zip(keys, row, strict=False)) for row in rows]
