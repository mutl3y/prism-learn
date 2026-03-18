"""Feedback-loop persistence and ranking helpers."""

from __future__ import annotations

from typing import Any

from .reporting_common import require_psycopg


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
    psycopg = require_psycopg()

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
    psycopg = require_psycopg()

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
