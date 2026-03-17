#!/usr/bin/env python3
"""Render section feedback ranking report for future section tuning decisions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from learning_app_scaffold import fetch_section_feedback_ranking  # noqa: E402


def _resolve_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = os.getenv("POSTGRES_USER", "learning_user")
    password = os.getenv("POSTGRES_PASSWORD", "learning_pass_change_me")
    db_name = os.getenv("POSTGRES_DB", "learning_scans")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def render_markdown(rows: list[dict[str, object]]) -> str:
    lines = ["# Section Feedback Ranking Report", ""]
    lines.append(f"- Ranked sections: {len(rows)}")
    lines.append("")
    lines.append(
        "| Section ID | Feedback Count | Avg Score | Avg Quality | Avg Title Helpfulness | Avg Accuracy | Latest Feedback |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---|")

    if rows:
        for row in rows:
            lines.append(
                "| {section_id} | {feedback_count} | {avg_feedback_score:.3f} | {avg_section_quality:.3f} | {avg_title_helpfulness:.3f} | {avg_content_accuracy:.3f} | {latest_feedback_at} |".format(
                    section_id=str(row.get("section_id", "")).replace("|", "\\|"),
                    feedback_count=int(row.get("feedback_count") or 0),
                    avg_feedback_score=float(row.get("avg_feedback_score") or 0.0),
                    avg_section_quality=float(row.get("avg_section_quality") or 0.0),
                    avg_title_helpfulness=float(
                        row.get("avg_title_helpfulness") or 0.0
                    ),
                    avg_content_accuracy=float(row.get("avg_content_accuracy") or 0.0),
                    latest_feedback_at=str(row.get("latest_feedback_at") or "n/a"),
                )
            )
    else:
        lines.append("| none | 0 | 0.000 | 0.000 | 0.000 | 0.000 | n/a |")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--min-feedback",
        type=int,
        default=1,
        help="Only include sections with at least this many feedback rows (default: 1).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of ranked sections to return (default: 50).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Optional path to write markdown output.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        metavar="PATH",
        help="Write raw ranking rows to JSON.",
    )
    args = parser.parse_args()

    rows = fetch_section_feedback_ranking(
        _resolve_dsn(),
        min_feedback=max(1, int(args.min_feedback)),
        limit=max(1, int(args.limit)),
    )

    if args.output_json:
        output_json = Path(args.output_json)
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(rows, default=str, indent=2), encoding="utf-8"
        )
        print(f"Wrote JSON: {output_json}")

    markdown = render_markdown(rows)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"Wrote: {output_path}")
    else:
        print(markdown)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
