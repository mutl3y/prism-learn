#!/usr/bin/env python3
"""Generate focused scanner triage artifacts for a refresh run label.

This script consolidates the manual workflow used during refresh triage:
- resolve latest batch id for a run label
- export batch target URLs
- export prioritized unresolved-variable bug targets (TSV)
- write a concise markdown summary for quick review
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _resolve_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = os.getenv("POSTGRES_USER", "learning_user")
    password = os.getenv("POSTGRES_PASSWORD", "learning_pass_change_me")
    db_name = os.getenv("POSTGRES_DB", "learning_scans")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _require_psycopg() -> Any:
    try:
        import psycopg
    except Exception as exc:  # pragma: no cover - dependency/runtime guard
        raise RuntimeError("psycopg is required; install prism-learn dependencies") from exc
    return psycopg


def _slug(value: str) -> str:
    cleaned = [ch if (ch.isalnum() or ch in "-_") else "-" for ch in value]
    slug = "".join(cleaned).strip("-")
    return slug or "report"


def _fetch_batch_id(conn: Any, *, run_label: str) -> int:
    query = """
        SELECT id
        FROM learning.scan_batches
        WHERE run_label = %s
        ORDER BY id DESC
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(query, (run_label,))
        row = cur.fetchone()
    if not row:
        raise RuntimeError(f"No batch found for run label: {run_label}")
    return int(row[0])


def _fetch_batch_urls(conn: Any, *, batch_id: int) -> list[str]:
    query = """
        SELECT DISTINCT s.target
        FROM learning.scan_snapshots AS s
        WHERE s.batch_id = %s
        ORDER BY s.target
    """
    with conn.cursor() as cur:
        cur.execute(query, (batch_id,))
        rows = cur.fetchall()
    return [str(row[0]) for row in rows if row and row[0]]


def _fetch_bug_targets(
    conn: Any,
    *,
    batch_id: int,
    top_n: int,
    exclude_dummy: bool,
    exclude_deprecated: bool,
) -> list[dict[str, Any]]:
    filters = ["unresolved > 0"]
    if exclude_dummy:
        filters.append("LOWER(COALESCE(role_name, '')) NOT LIKE '%%dummy%%'")
    if exclude_deprecated:
        filters.append("UPPER(COALESCE(description, '')) NOT LIKE 'DEPRECATED:%%'")

    where_sql = " AND ".join(filters)

    query = f"""
        WITH raw AS (
            SELECT
                s.target,
                s.scan_payload->'metadata'->>'role_name' AS role_name,
                s.scan_payload->'metadata'->>'description' AS description,
                COALESCE((s.scan_payload->'metadata'->'scanner_counters'->>'total_variables')::int, 0) AS total_vars,
                COALESCE((s.scan_payload->'metadata'->'scanner_counters'->>'unresolved_variables')::int, 0) AS unresolved,
                COALESCE((s.scan_payload->'metadata'->'scanner_counters'->>'ambiguous_variables')::int, 0) AS ambiguous_vars,
                COALESCE((s.scan_payload->'metadata'->'scanner_counters'->'provenance_issue_categories'->>'unresolved_dynamic_include_vars')::int, 0) AS p_unresolved_dynamic_include_vars,
                COALESCE((s.scan_payload->'metadata'->'scanner_counters'->'provenance_issue_categories'->>'unresolved_readme_documented_only')::int, 0) AS p_unresolved_readme_documented_only,
                COALESCE((s.scan_payload->'metadata'->'scanner_counters'->'provenance_issue_categories'->>'unresolved_no_static_definition')::int, 0) AS p_unresolved_no_static_definition,
                COALESCE((s.scan_payload->'metadata'->'scanner_counters'->'provenance_issue_categories'->>'ambiguous_set_fact_runtime')::int, 0) AS p_ambiguous_set_fact_runtime
            FROM learning.scan_snapshots AS s
            WHERE s.batch_id = %s
        )
        SELECT
            target,
            role_name,
            description,
            unresolved,
            total_vars,
            CASE WHEN total_vars > 0 THEN unresolved::numeric / total_vars::numeric ELSE 0::numeric END AS unresolved_ratio,
            p_unresolved_dynamic_include_vars,
            p_unresolved_readme_documented_only,
            p_unresolved_no_static_definition,
            p_ambiguous_set_fact_runtime,
            ambiguous_vars
        FROM raw
        WHERE {where_sql}
        ORDER BY unresolved DESC, unresolved_ratio DESC, total_vars DESC, target ASC
        LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute(query, (batch_id, top_n))
        rows = cur.fetchall()

    columns = [
        "target",
        "role_name",
        "description",
        "unresolved",
        "total_vars",
        "unresolved_ratio",
        "p_unresolved_dynamic_include_vars",
        "p_unresolved_readme_documented_only",
        "p_unresolved_no_static_definition",
        "p_ambiguous_set_fact_runtime",
        "ambiguous_vars",
    ]
    results: list[dict[str, Any]] = []
    for row in rows:
        item = {key: value for key, value in zip(columns, row)}
        item["target"] = str(item["target"])
        item["role_name"] = str(item["role_name"] or "")
        item["description"] = str(item["description"] or "")
        item["unresolved"] = int(item["unresolved"] or 0)
        item["total_vars"] = int(item["total_vars"] or 0)
        item["unresolved_ratio"] = float(item["unresolved_ratio"] or 0.0)
        item["p_unresolved_dynamic_include_vars"] = int(
            item["p_unresolved_dynamic_include_vars"] or 0
        )
        item["p_unresolved_readme_documented_only"] = int(
            item["p_unresolved_readme_documented_only"] or 0
        )
        item["p_unresolved_no_static_definition"] = int(
            item["p_unresolved_no_static_definition"] or 0
        )
        item["p_ambiguous_set_fact_runtime"] = int(
            item["p_ambiguous_set_fact_runtime"] or 0
        )
        item["ambiguous_vars"] = int(item["ambiguous_vars"] or 0)
        results.append(item)

    return results


def _write_urls(path: Path, urls: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(urls)
    if content:
        content += "\n"
    path.write_text(content, encoding="utf-8")


def _write_bug_targets_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "target",
        "unresolved",
        "total_vars",
        "ratio",
        "p_unresolved_dynamic_include_vars",
        "p_unresolved_readme_documented_only",
        "p_unresolved_no_static_definition",
        "p_ambiguous_set_fact_runtime",
        "ambiguous_vars",
    ]
    lines = ["\t".join(header)]

    for row in rows:
        lines.append(
            "\t".join(
                [
                    row["target"],
                    str(row["unresolved"]),
                    str(row["total_vars"]),
                    f"{row['unresolved_ratio']:.3f}",
                    str(row["p_unresolved_dynamic_include_vars"]),
                    str(row["p_unresolved_readme_documented_only"]),
                    str(row["p_unresolved_no_static_definition"]),
                    str(row["p_ambiguous_set_fact_runtime"]),
                    str(row["ambiguous_vars"]),
                ]
            )
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _render_summary_markdown(
    *,
    run_label: str,
    batch_id: int,
    url_count: int,
    rows: list[dict[str, Any]],
    urls_path: Path,
    tsv_path: Path,
    exclude_dummy: bool,
    exclude_deprecated: bool,
) -> str:
    lines = [f"# Refresh Triage Summary ({run_label})", ""]
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- Run label: `{run_label}`")
    lines.append(f"- Batch id: `{batch_id}`")
    lines.append(f"- Targets in batch: `{url_count}`")
    lines.append(f"- Exclude role name containing `dummy`: `{str(exclude_dummy).lower()}`")
    lines.append(
        f"- Exclude description prefixed `DEPRECATED:`: `{str(exclude_deprecated).lower()}`"
    )
    lines.append(f"- URL list: `{urls_path}`")
    lines.append(f"- Bug target TSV: `{tsv_path}`")
    lines.append("")

    lines.append("## Prioritized Scanner Bug Targets")
    lines.append("")
    lines.append(
        "| # | Target | unresolved | total_vars | ratio | dynamic_include | readme_only | no_static_def | ambiguous_set_fact |"
    )
    lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|")

    if rows:
        for idx, row in enumerate(rows, start=1):
            lines.append(
                "| {idx} | {target} | {unresolved} | {total_vars} | {ratio:.3f} | {dyn} | {readme} | {nostatic} | {ambig_sf} |".format(
                    idx=idx,
                    target=row["target"].replace("|", "\\|"),
                    unresolved=row["unresolved"],
                    total_vars=row["total_vars"],
                    ratio=row["unresolved_ratio"],
                    dyn=row["p_unresolved_dynamic_include_vars"],
                    readme=row["p_unresolved_readme_documented_only"],
                    nostatic=row["p_unresolved_no_static_definition"],
                    ambig_sf=row["p_ambiguous_set_fact_runtime"],
                )
            )
    else:
        lines.append("| 1 | none | 0 | 0 | 0.000 | 0 | 0 | 0 | 0 |")

    lines.append("")
    lines.append("## Suggested Buckets")
    lines.append("")

    bucket_a = [
        row["target"]
        for row in rows
        if row["p_unresolved_dynamic_include_vars"] >= max(3, row["unresolved"] // 3)
    ]
    bucket_b = [
        row["target"]
        for row in rows
        if row["p_unresolved_readme_documented_only"] >= max(3, row["unresolved"] // 3)
    ]
    bucket_c = [
        row["target"]
        for row in rows
        if row["p_unresolved_no_static_definition"] >= max(3, row["unresolved"] // 2)
    ]
    bucket_d = [row["target"] for row in rows if row["p_ambiguous_set_fact_runtime"] >= 3]

    def _append_bucket(title: str, items: list[str]) -> None:
        lines.append(f"- {title}")
        if not items:
            lines.append("  - none")
            return
        for target in items:
            lines.append(f"  - `{target}`")

    _append_bucket("Bucket A: Dynamic include vars attribution", bucket_a)
    _append_bucket("Bucket B: README-only extraction over-capture", bucket_b)
    _append_bucket("Bucket C: No static definition false positives", bucket_c)
    _append_bucket("Bucket D: set_fact ambiguity inflation", bucket_d)

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-label",
        required=True,
        help="Run label to triage (latest matching batch id is used).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=12,
        help="Number of bug targets to include (default: 12).",
    )
    parser.add_argument(
        "--output-dir",
        default=".local/tmp",
        help="Directory for generated files (default: .local/tmp).",
    )
    parser.add_argument(
        "--exclude-dummy",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exclude rows where role name contains 'dummy' (default: true).",
    )
    parser.add_argument(
        "--exclude-deprecated",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exclude rows where description starts with 'DEPRECATED:' (default: true).",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="Optional output filename prefix (default: run-label slug).",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = args.prefix or _slug(args.run_label)

    urls_path = out_dir / f"{prefix}_urls.txt"
    tsv_path = out_dir / f"{prefix}_bug_targets.tsv"
    summary_path = out_dir / f"{prefix}_scanner_bug_list.md"

    psycopg = _require_psycopg()
    with psycopg.connect(_resolve_dsn()) as conn:
        batch_id = _fetch_batch_id(conn, run_label=args.run_label)
        urls = _fetch_batch_urls(conn, batch_id=batch_id)
        rows = _fetch_bug_targets(
            conn,
            batch_id=batch_id,
            top_n=args.top_n,
            exclude_dummy=args.exclude_dummy,
            exclude_deprecated=args.exclude_deprecated,
        )

    _write_urls(urls_path, urls)
    _write_bug_targets_tsv(tsv_path, rows)

    summary = _render_summary_markdown(
        run_label=args.run_label,
        batch_id=batch_id,
        url_count=len(urls),
        rows=rows,
        urls_path=urls_path,
        tsv_path=tsv_path,
        exclude_dummy=args.exclude_dummy,
        exclude_deprecated=args.exclude_deprecated,
    )
    summary_path.write_text(summary, encoding="utf-8")

    print(f"Wrote: {urls_path}")
    print(f"Wrote: {tsv_path}")
    print(f"Wrote: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
