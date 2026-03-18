"""Before/after quality delta reporting helpers."""

from __future__ import annotations

from typing import Any

from .reporting_common import coerce_json_document, require_psycopg


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_doc_quality_metrics(payload: Any) -> dict[str, Any]:
    document = coerce_json_document(payload)
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


def fetch_doc_quality_report(
    dsn: str,
    *,
    batch_id: int | None = None,
    run_label: str | None = None,
) -> dict[str, Any]:
    """Return before/after document quality metrics from persisted snapshots."""
    psycopg = require_psycopg()

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
