#!/usr/bin/env python3
"""Aggregate persisted style-guide heading observations into a markdown report."""

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

from learning_app_scaffold import fetch_section_title_report  # noqa: E402


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
    return ", ".join(
        f"{_strip_backticks(str(item['title']))} ({item['count']})"
        for item in items[:limit]
    )


def _format_targets(targets: list[str]) -> str:
    if not targets:
        return "-"
    return ", ".join(targets)


def _strip_backticks(text: str) -> str:
    """Remove markdown inline-code ticks from rendered report text."""
    return text.replace("`", "")


def _find_backtick_title_candidates(
    report: dict[str, object], *, top_variants: int
) -> list[dict[str, object]]:
    """Return section/title entries whose observed heading text contains backticks."""
    candidates: list[dict[str, object]] = []

    for section in report.get("sections", []):
        section_id = str(section.get("section_id") or "")
        section_label = str(section.get("display_title") or section_id)
        for variant in section.get("titles", []):
            title = str(variant.get("title") or "")
            if "`" not in title:
                continue
            candidates.append(
                {
                    "kind": "known_section_variant",
                    "group": section_label,
                    "normalized": section_id,
                    "title": _strip_backticks(title),
                    "count": int(variant.get("count") or 0),
                }
            )

    for item in report.get("unknown_titles", []):
        normalized = str(item.get("normalized_title") or "")
        for variant in item.get("titles", []):
            title = str(variant.get("title") or "")
            if "`" not in title:
                continue
            candidates.append(
                {
                    "kind": "unknown_title_variant",
                    "group": normalized,
                    "normalized": normalized,
                    "title": _strip_backticks(title),
                    "count": int(variant.get("count") or 0),
                }
            )

    candidates.sort(key=lambda item: (-(int(item["count"])), str(item["title"])))
    return candidates[:top_variants]


def render_markdown(
    report: dict[str, object],
    *,
    top_variants: int,
    min_section_count: int = 1,
    min_unknown_count: int = 1,
) -> str:
    selection = report["selection"]
    backtick_candidates = _find_backtick_title_candidates(
        report,
        top_variants=top_variants,
    )

    lines = ["# Style Section Title Report", ""]
    lines.append(f"- Data source: {selection.get('source', 'raw')}")
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
    if min_section_count > 1 or min_unknown_count > 1:
        filter_parts = []
        if min_section_count > 1:
            filter_parts.append(f"min section count={min_section_count}")
        if min_unknown_count > 1:
            filter_parts.append(f"min unknown count={min_unknown_count}")
        lines.append(f"- Filters: {', '.join(filter_parts)}")
    lines.append(f"- Backtick title variants detected: {len(backtick_candidates)}")
    lines.append("")

    lines.append("## Known Section Variants")
    lines.append("")
    lines.append("| Section | Count | Targets | Top observed titles |")
    lines.append("|---|---:|---:|---|")
    for section in report["sections"]:
        if not section["known"]:
            continue
        if int(section["count"]) < min_section_count:
            continue
        sid = section["section_id"]
        display = section.get("display_title")
        section_label = f"{display} (`{sid}`)" if display else sid
        lines.append(
            "| {section_label} | {count} | {distinct_targets} | {titles} |".format(
                section_label=section_label,
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
    unknown_titles = [
        item
        for item in report["unknown_titles"]
        if int(item["count"]) >= min_unknown_count
    ]
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

    if backtick_candidates:
        lines.append("")
        lines.append("## Backtick Title Variant Checks")
        lines.append("")
        lines.append("| Kind | Group | Observed title | Count |")
        lines.append("|---|---|---|---:|")
        for item in backtick_candidates:
            lines.append(
                "| {kind} | {group} | {title} | {count} |".format(
                    kind=str(item["kind"]).replace("|", "\\|"),
                    group=str(item["group"]).replace("|", "\\|"),
                    title=str(item["title"]).replace("|", "\\|"),
                    count=item["count"],
                )
            )

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
    parser.add_argument(
        "--min-section-count",
        type=int,
        default=1,
        help="Hide known-section rows whose snapshot count is below this threshold (default: 1).",
    )
    parser.add_argument(
        "--min-unknown-count",
        type=int,
        default=1,
        help="Hide unknown-title rows whose snapshot count is below this threshold (default: 1).",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        metavar="PATH",
        help="Write the raw report dict as JSON to PATH (useful as offline input for learning_resolve_unknowns.py).",
    )
    parser.add_argument(
        "--source",
        choices=("raw", "reduced"),
        default="raw",
        help="Choose report source: raw scan_snapshots payloads or reduced materialized table (default: raw).",
    )
    args = parser.parse_args()

    report = fetch_section_title_report(
        _resolve_dsn(),
        batch_id=args.batch_id,
        run_label=args.run_label,
        latest_per_target=not args.all_snapshots,
        source=args.source,
    )

    if args.output_json:
        json_path = Path(args.output_json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(report, default=str, indent=2), encoding="utf-8"
        )
        print(f"Wrote JSON: {json_path}")

    markdown = render_markdown(
        report,
        top_variants=args.top_variants,
        min_section_count=args.min_section_count,
        min_unknown_count=args.min_unknown_count,
    )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        print(f"Wrote: {output_path}")
    else:
        try:
            print(markdown, end="")
            sys.stdout.flush()
        except BrokenPipeError:
            sys.stdout = open(os.devnull, "w")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
