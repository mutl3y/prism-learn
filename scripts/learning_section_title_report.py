#!/usr/bin/env python3
"""Aggregate persisted style-guide heading observations into a markdown report."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from learning_app_scaffold import fetch_section_title_report


def _resolve_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = os.getenv("POSTGRES_USER", "learning_user")
    password = os.getenv("POSTGRES_PASSWORD", "learning_pass_change_me")
    db_name = os.getenv("POSTGRES_DB", "learning_scans")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _format_variant_list(items: list[dict[str, object]], limit: int) -> str:
    if not items:
        return "-"
    return ", ".join(f"{item['title']} ({item['count']})" for item in items[:limit])


def _format_targets(targets: list[str]) -> str:
    if not targets:
        return "-"
    return ", ".join(targets)


def render_markdown(report: dict[str, object], *, top_variants: int) -> str:
    selection = report["selection"]
    lines = ["# Style Section Title Report", ""]
    lines.append(
        f"- Snapshot selection: {'latest snapshot per target' if selection['latest_per_target'] else 'all matching snapshots'}"
    )
    lines.append(f"- Snapshot rows considered: {report['snapshot_count']}")
    lines.append(f"- Distinct targets: {report['distinct_targets']}")
    if selection["run_label"]:
        lines.append(f"- Run label filter: {selection['run_label']}")
    if selection["batch_id"] is not None:
        lines.append(f"- Batch id filter: {selection['batch_id']}")
    lines.append(
        f"- Aggregated sections: total={report['total_sections']}, known={report['known_sections']}, unknown={report['unknown_sections']}"
    )
    lines.append(
        "- Variant counts below mean the number of persisted snapshots in which that title was observed."
    )
    lines.append("")

    lines.append("## Known Section Variants")
    lines.append("")
    lines.append("| Section ID | Count | Targets | Top observed titles |")
    lines.append("|---|---:|---:|---|")
    for section in report["sections"]:
        if not section["known"]:
            continue
        lines.append(
            "| {section_id} | {count} | {distinct_targets} | {titles} |".format(
                section_id=section["section_id"],
                count=section["count"],
                distinct_targets=section["distinct_targets"],
                titles=_format_variant_list(section["titles"], top_variants).replace(
                    "|", "\\|"
                ),
            )
        )

    lines.append("")
    lines.append("## Unknown Heading Candidates")
    lines.append("")
    lines.append(
        "| Normalized title | Snapshots | Targets | Example titles | Sample targets |"
    )
    lines.append("|---|---:|---:|---|---|")
    unknown_titles = report["unknown_titles"]
    if unknown_titles:
        for item in unknown_titles:
            lines.append(
                "| {normalized_title} | {count} | {distinct_targets} | {titles} | {targets} |".format(
                    normalized_title=str(item["normalized_title"]).replace("|", "\\|"),
                    count=item["count"],
                    distinct_targets=item["distinct_targets"],
                    titles=_format_variant_list(item["titles"], top_variants).replace(
                        "|", "\\|"
                    ),
                    targets=_format_targets(item["sample_targets"]).replace("|", "\\|"),
                )
            )
    else:
        lines.append("| none | 0 | 0 | - | - |")

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
        "--all-snapshots",
        action="store_true",
        help="Aggregate every matching snapshot instead of only the latest snapshot per target.",
    )
    parser.add_argument(
        "--top-variants",
        type=int,
        default=5,
        help="How many title variants to show per section in the markdown output.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Optional path to write the markdown report to.",
    )
    args = parser.parse_args()

    report = fetch_section_title_report(
        _resolve_dsn(),
        batch_id=args.batch_id,
        run_label=args.run_label,
        latest_per_target=not args.all_snapshots,
    )
    markdown = render_markdown(report, top_variants=args.top_variants)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"Wrote: {output_path}")
    else:
        print(markdown, end="")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
