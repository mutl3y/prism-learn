#!/usr/bin/env python3
"""Aggregate persisted before/after doc quality metrics into a markdown report."""

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

from prism_learn import fetch_doc_quality_report  # noqa: E402


def _resolve_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = os.getenv("POSTGRES_USER", "learning_user")
    password = os.getenv("POSTGRES_PASSWORD", "learning_pass_change_me")
    db_name = os.getenv("POSTGRES_DB", "learning_scans")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _fmt_delta(value: object, *, digits: int = 0) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:+.{digits}f}" if digits > 0 else f"{value:+.0f}"
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{ivalue:+d}"


def render_markdown(report: dict[str, object], *, top_targets: int = 20) -> str:
    selection = report.get("selection") or {}
    trend_counts = report.get("trend_counts") or {}

    lines = ["# Doc Quality Before/After Report", ""]
    lines.append(
        "- Snapshot selection: latest snapshot with previous baseline per target"
    )
    lines.append(f"- Targets considered: {report.get('target_count', 0)}")
    lines.append(
        f"- Targets with previous snapshot: {report.get('targets_with_previous', 0)}"
    )
    if selection.get("run_label"):
        lines.append(f"- Run label filter: {selection['run_label']}")
    if selection.get("batch_id") is not None:
        lines.append(f"- Batch id filter: {selection['batch_id']}")
    lines.append(
        "- Trend counts: "
        f"improved={trend_counts.get('improved', 0)}, "
        f"regressed={trend_counts.get('regressed', 0)}, "
        f"stable={trend_counts.get('stable', 0)}, "
        f"baseline={trend_counts.get('baseline', 0)}"
    )
    lines.append("")

    lines.append("## Target Deltas")
    lines.append("")
    lines.append(
        "| Target | Trend | Resolved Δ | Unresolved Δ | Ambiguity Δ | Confidence Δ | Current (vars/resolved/conf) |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---|")

    rows = (report.get("targets") or [])[:top_targets]
    if rows:
        for item in rows:
            current = item.get("current") or {}
            delta = item.get("delta") or {}
            confidence = current.get("confidence_avg")
            confidence_label = "n/a"
            if isinstance(confidence, (float, int)):
                confidence_label = f"{float(confidence):.3f}"

            lines.append(
                "| {target} | {trend} | {resolved_delta} | {unresolved_delta} | {ambiguity_delta} | {confidence_delta} | {current_summary} |".format(
                    target=str(item.get("target", "")).replace("|", "\\|"),
                    trend=str(item.get("trend", "baseline")),
                    resolved_delta=_fmt_delta(delta.get("resolved_count_delta")),
                    unresolved_delta=_fmt_delta(delta.get("unresolved_count_delta")),
                    ambiguity_delta=_fmt_delta(delta.get("ambiguity_count_delta")),
                    confidence_delta=_fmt_delta(
                        delta.get("confidence_avg_delta"), digits=3
                    ),
                    current_summary=(
                        f"{int(current.get('variable_count') or 0)}/"
                        f"{int(current.get('resolved_count') or 0)}/"
                        f"{confidence_label}"
                    ),
                )
            )
    else:
        lines.append("| none | baseline | n/a | n/a | n/a | n/a | n/a |")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-id",
        type=int,
        default=None,
        help="Restrict the report to snapshots from a specific batch id.",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Restrict the report to snapshots whose batch row has this run label.",
    )
    parser.add_argument(
        "--top-targets",
        type=int,
        default=20,
        help="How many targets to include in the markdown table (default: 20).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Optional path to write the markdown report to.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        metavar="PATH",
        help="Write the raw report dict as JSON to PATH.",
    )
    args = parser.parse_args()

    report = fetch_doc_quality_report(
        _resolve_dsn(),
        batch_id=args.batch_id,
        run_label=args.run_label,
    )

    if args.output_json:
        json_path = Path(args.output_json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(report, default=str, indent=2), encoding="utf-8"
        )
        print(f"Wrote JSON: {json_path}")

    markdown = render_markdown(report, top_targets=args.top_targets)
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
