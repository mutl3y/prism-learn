#!/usr/bin/env python3
"""Helper workflow for LLM section-title review and alias application.

Subcommands:
- review: trigger learning_resolve_unknowns.py with common options.
- apply: parse generated YAML candidates, upsert approved aliases to Postgres,
         and optionally trigger reduced-table rematerialization.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _require_psycopg():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is required for alias apply. Install it with `pip install psycopg[binary]`."
        ) from exc
    return psycopg


def _resolve_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = os.getenv("POSTGRES_USER", "learning_user")
    password = os.getenv("POSTGRES_PASSWORD", "learning_pass_change_me")
    db_name = os.getenv("POSTGRES_DB", "learning_scans")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def _run_review(args: argparse.Namespace) -> int:
    cmd: list[str] = [
        sys.executable,
        str(SCRIPTS_DIR / "learning_resolve_unknowns.py"),
        "--min-count",
        str(args.min_count),
        "--batch-size",
        str(args.batch_size),
        "--rpm",
        str(args.rpm),
        "--model",
        args.model,
    ]

    if args.input_json:
        cmd.extend(["--input-json", args.input_json])
    elif args.dsn:
        cmd.extend(["--dsn", args.dsn])

    if args.output_yaml:
        cmd.extend(["--output-yaml", args.output_yaml])
    if args.output_report:
        cmd.extend(["--output-report", args.output_report])

    print("Running:", " ".join(cmd), file=sys.stderr)
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    return int(result.returncode)


def _parse_candidate_yaml(
    path: Path, include_novel: bool
) -> list[tuple[str, str, str, int]]:
    """Parse helper-generated YAML comments + mappings.

    Returns tuples: (normalized_title, section_id, mode, count)
    where mode is one of alias_of/novel/other and count is the
    observed occurrence count from the inline YAML comment.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    current_mode = "other"
    results: list[tuple[str, str, str, int]] = []

    mapping_re = re.compile(
        r'^\s+"(?P<title>.+)":\s+(?P<section>.+?)\s*(?:#\s*count=(?P<count>\d+))?\s*$'
    )
    count_re = re.compile(r"#\s*count=(\d+)")

    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("#") and "alias_of" in stripped:
            current_mode = "alias_of"
            continue
        if stripped.startswith("#") and "novel" in stripped:
            current_mode = "novel"
            continue

        match = mapping_re.match(line)
        if not match:
            continue

        title = match.group("title").strip()
        # section_id may include spaces (e.g. "database backups (optional)")
        # strip any trailing comment from the section field
        raw_section = match.group("section")
        section_id = count_re.sub("", raw_section).strip()

        if current_mode == "novel" and not include_novel:
            continue

        if not title or not section_id:
            continue

        count_str = match.group("count")
        count = int(count_str) if count_str else 0

        results.append((title, section_id, current_mode, count))

    dedup: dict[str, tuple[str, str, str, int]] = {}
    for title, section_id, mode, count in results:
        dedup[title] = (title, section_id, mode, count)
    return list(dedup.values())


def _upsert_aliases(
    dsn: str,
    aliases: list[tuple[str, str, str, int]],
    *,
    source: str,
    dry_run: bool,
    min_count: int = 0,
) -> int:
    if not aliases:
        return 0

    psycopg = _require_psycopg()
    upserted = 0

    sql = """
        INSERT INTO learning.section_title_aliases (
            normalized_title,
            section_id,
            source,
            approved_at_utc,
            metadata
        ) VALUES (%s, %s, %s, NOW(), %s::jsonb)
        ON CONFLICT (normalized_title) DO UPDATE
        SET
            section_id = EXCLUDED.section_id,
            source = EXCLUDED.source,
            approved_at_utc = NOW(),
            metadata = EXCLUDED.metadata
    """

    with psycopg.connect(dsn) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS learning")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS learning.section_title_aliases (
                    normalized_title TEXT PRIMARY KEY,
                    section_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual_review',
                    approved_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                    CHECK (length(trim(normalized_title)) > 0),
                    CHECK (length(trim(section_id)) > 0)
                )
                """
            )

            for title, section_id, mode, count in aliases:
                if min_count > 0 and count < min_count:
                    continue
                metadata = '{"mode":"' + mode + '","count":' + str(count) + "}"
                if dry_run:
                    print(
                        f"[dry-run] alias {title!r} -> {section_id} (mode={mode}, count={count})",
                        file=sys.stderr,
                    )
                    upserted += 1
                    continue

                cur.execute(sql, (title, section_id, source, metadata))
                upserted += 1

        if dry_run:
            conn.rollback()
        else:
            conn.commit()

    return upserted


def _run_export_aliases(args: argparse.Namespace) -> int:
    """Export learned aliases from Postgres to a YAML file in app data."""
    dsn = args.dsn or _resolve_dsn()
    psycopg = _require_psycopg()

    output_path = Path(args.output)
    min_count = int(getattr(args, "min_count", 0))

    sql = """
        SELECT normalized_title, section_id
        FROM learning.section_title_aliases
        WHERE (%s = 0)
           OR COALESCE(NULLIF(metadata->>'count', ''), '0')::int >= %s
        ORDER BY section_id ASC, normalized_title ASC
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (min_count, min_count))
            rows = cur.fetchall()

    lines = [
        "# Learned aliases exported from learning.section_title_aliases",
        "# Review and merge into src/ansible_role_doc/data/section_aliases.yml",
        f"# Exported by learning_alias_helper.py on {output_path}",
        "",
        "section_aliases:",
    ]

    for normalized_title, section_id in rows:
        title = str(normalized_title).replace('"', '\\"')
        sid = str(section_id).strip()
        lines.append(f'  "{title}": {sid}')

    output_text = "\n".join(lines) + "\n"

    if args.dry_run:
        print(output_text)
        print(
            f"[dry-run] Would export {len(rows)} aliases to {output_path}",
            file=sys.stderr,
        )
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_text, encoding="utf-8")
    print(f"Exported {len(rows)} aliases to {output_path}", file=sys.stderr)
    return 0


def _parse_section_aliases_yaml(path: Path) -> tuple[list[str], dict[str, str]]:
    """Parse section_aliases YAML into (header_lines, alias_map)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    header_lines: list[str] = []
    alias_map: dict[str, str] = {}

    in_aliases = False
    alias_re = re.compile(r'^\s+"(?P<title>.+)":\s+(?P<section>[^#\n]+?)\s*(?:#.*)?$')

    for line in lines:
        stripped = line.strip()
        if not in_aliases:
            header_lines.append(line)
            if stripped == "section_aliases:":
                in_aliases = True
            continue

        match = alias_re.match(line)
        if not match:
            continue
        title = match.group("title").strip()
        section_id = match.group("section").strip()
        if title and section_id:
            alias_map[title] = section_id

    return header_lines, alias_map


def _render_section_aliases_yaml(
    header_lines: list[str], alias_map: dict[str, str]
) -> str:
    """Render grouped section_aliases YAML with deterministic ordering."""
    by_section: dict[str, list[str]] = {}
    for title, section_id in alias_map.items():
        by_section.setdefault(section_id, []).append(title)

    out_lines: list[str] = list(header_lines)
    if out_lines and out_lines[-1].strip() != "":
        out_lines.append("")

    for section_id in sorted(by_section):
        out_lines.append(f"  # -- {section_id} {'-' * 60}")
        for title in sorted(by_section[section_id]):
            safe_title = title.replace('"', '\\"')
            out_lines.append(f'  "{safe_title}": {section_id}')
        out_lines.append("")

    while out_lines and out_lines[-1] == "":
        out_lines.pop()

    return "\n".join(out_lines) + "\n"


def _run_merge_aliases(args: argparse.Namespace) -> int:
    """Merge learned aliases file into canonical section_aliases YAML."""
    base_path = Path(args.base)
    learned_path = Path(args.learned)
    output_path = Path(args.output)

    if not base_path.exists():
        print(f"error: base aliases file not found: {base_path}", file=sys.stderr)
        return 1
    if not learned_path.exists():
        print(f"error: learned aliases file not found: {learned_path}", file=sys.stderr)
        return 1

    header_lines, base_aliases = _parse_section_aliases_yaml(base_path)
    _learned_header, learned_aliases = _parse_section_aliases_yaml(learned_path)

    added = 0
    updated = 0
    merged = dict(base_aliases)
    for title, section_id in learned_aliases.items():
        existing = merged.get(title)
        if existing is None:
            added += 1
        elif existing != section_id:
            updated += 1
        merged[title] = section_id

    rendered = _render_section_aliases_yaml(header_lines, merged)

    print(
        f"Merged aliases: base={len(base_aliases)}, learned={len(learned_aliases)}, "
        f"added={added}, updated={updated}, total={len(merged)}",
        file=sys.stderr,
    )

    if args.dry_run:
        print("[dry-run] No file changes written.", file=sys.stderr)
        return 0

    output_path.write_text(rendered, encoding="utf-8")
    print(f"Wrote merged aliases: {output_path}", file=sys.stderr)
    return 0


def _run_materialize(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "learning_materialize_sections.py"),
        "--batch-size",
        str(args.materialize_batch_size),
        "--reapply-aliases",
    ]
    if args.dsn:
        cmd.extend(["--dsn", args.dsn])

    print("Running:", " ".join(cmd), file=sys.stderr)
    result = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    return int(result.returncode)


def _run_rename_section(args: argparse.Namespace) -> int:
    """Rename a section_id across all Postgres tables."""
    old_id = args.old_id
    new_id = args.new_id
    dsn = args.dsn or _resolve_dsn()
    psycopg = _require_psycopg()

    with psycopg.connect(dsn) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            # Count what will be affected
            cur.execute(
                "SELECT COUNT(*) FROM learning.section_title_aliases WHERE section_id = %s",
                (old_id,),
            )
            alias_count = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM learning.scan_snapshot_sections WHERE effective_section_id = %s",
                (old_id,),
            )
            effective_count = cur.fetchone()[0]

            cur.execute(
                "SELECT COUNT(*) FROM learning.scan_snapshot_sections WHERE raw_section_id = %s",
                (old_id,),
            )
            raw_count = cur.fetchone()[0]

            print(
                f"Section rename: {old_id!r} -> {new_id!r}",
                file=sys.stderr,
            )
            print(
                f"  section_title_aliases.section_id:          {alias_count} rows",
                file=sys.stderr,
            )
            print(
                f"  scan_snapshot_sections.effective_section_id: {effective_count} rows",
                file=sys.stderr,
            )
            print(
                f"  scan_snapshot_sections.raw_section_id:       {raw_count} rows",
                file=sys.stderr,
            )

            if args.dry_run:
                print("[dry-run] No changes made.", file=sys.stderr)
                conn.rollback()
                return 0

            cur.execute(
                "UPDATE learning.section_title_aliases SET section_id = %s WHERE section_id = %s",
                (new_id, old_id),
            )
            cur.execute(
                "UPDATE learning.scan_snapshot_sections SET effective_section_id = %s WHERE effective_section_id = %s",
                (new_id, old_id),
            )
            cur.execute(
                "UPDATE learning.scan_snapshot_sections SET raw_section_id = %s WHERE raw_section_id = %s",
                (new_id, old_id),
            )
        conn.commit()

    print("Done.", file=sys.stderr)
    return 0


def _title_to_section_id(title: str) -> str:
    """Normalise a human title to a snake_case section id candidate.

    e.g. "Role Variables" -> "role_variables"
         "Example Playbook" -> "example_playbook"
    """
    slug = title.lower().strip()
    # replace any non-alphanumeric run with an underscore
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def _run_suggest_canonical(args: argparse.Namespace) -> int:
    """Show the most popular observed title per section_id.

    Queries scan_snapshot_sections grouping by raw_section_id (default) or
    effective_section_id.  raw_section_id reflects what the scanner detected
    before any alias layering, which is the most honest basis for deciding
    what a section should be named.  Use effective to see post-alias groupings.
    """
    dsn = args.dsn or _resolve_dsn()
    psycopg = _require_psycopg()

    by_col = "raw_section_id" if args.by == "raw" else "effective_section_id"

    sql = f"""
        SELECT
            {by_col} AS section_id,
            title AS top_title,
            title_count,
            section_total
        FROM (
            SELECT
                {by_col},
                title,
                COUNT(*) AS title_count,
                SUM(COUNT(*)) OVER (PARTITION BY {by_col}) AS section_total,
                ROW_NUMBER() OVER (
                    PARTITION BY {by_col}
                    ORDER BY COUNT(*) DESC
                ) AS rn
            FROM learning.scan_snapshot_sections
            WHERE {by_col} IS NOT NULL
              AND title IS NOT NULL
            GROUP BY {by_col}, title
        ) ranked
        WHERE rn = 1
        ORDER BY section_total DESC
    """

    min_count = getattr(args, "min_count", 0)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()

    if not rows:
        print(
            "No section data found. Run learning_materialize_sections.py first.",
            file=sys.stderr,
        )
        return 1

    label = "raw_section_id" if args.by == "raw" else "effective_section_id"
    print(f"Grouping by: {label}", file=sys.stderr)
    print(f"{'section_id':<40} {'total':>8}  {'top_title':<50} {'top_count':>10}")
    print("-" * 115)

    yaml_lines: list[str] = []
    for section_id, top_title, top_count, total in rows:
        if min_count and total < min_count:
            continue
        top_title_trunc = (top_title[:47] + "...") if len(top_title) > 50 else top_title
        print(f"{section_id:<40} {total:>8}  {top_title_trunc:<50} {top_count:>10}")
        if args.output_yaml:
            display_title = top_title if top_title else section_id
            # Escape any YAML-sensitive chars in the display title
            safe_title = display_title.replace('"', '\\"')
            yaml_lines.append(
                f'  {section_id}: "{safe_title}"'
                + f"  # total={total}, top_count={top_count}"
            )

    if args.output_yaml and yaml_lines:
        out = Path(args.output_yaml)
        header = (
            "# Suggested display titles — review values then run apply-display-titles.\n"
            "# Delete or comment out lines you do not want to set.\n"
            "# The section_id (left) is the stable internal key; the value is the human label.\n"
            f"# Generated by: suggest-canonical --by {args.by}\n"
            "\n"
            "display_titles:\n"
        )
        out.write_text(header + "\n".join(yaml_lines) + "\n", encoding="utf-8")
        print(f"Wrote display title suggestions: {out}", file=sys.stderr)

    return 0


def _run_apply_display_titles(args: argparse.Namespace) -> int:
    """Upsert display titles from a YAML file into learning.section_display_titles."""
    yaml_path = Path(args.yaml)
    if not yaml_path.exists():
        print(f"error: YAML file not found: {yaml_path}", file=sys.stderr)
        return 1

    content = yaml_path.read_text(encoding="utf-8")
    titles: list[tuple[str, str]] = []
    in_block = False
    # matches:  section_id: "Display Title"  # optional comment
    #       or: section_id: Display Title without quotes
    entry_re = re.compile(r'^\s+([a-zA-Z0-9_.() -]+?):\s+"?([^"#\n]+?)"?\s*(?:#.*)?$')
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("display_titles:"):
            in_block = True
            continue
        if not in_block:
            continue
        if stripped.startswith("#") or not stripped:
            continue
        m = entry_re.match(line)
        if not m:
            continue
        section_id = m.group(1).strip()
        display_title = m.group(2).strip().strip('"')
        if section_id and display_title:
            titles.append((section_id, display_title))

    if not titles:
        print("No display titles found in YAML.", file=sys.stderr)
        return 0

    dsn = args.dsn or _resolve_dsn()
    psycopg = _require_psycopg()

    print(f"{len(titles)} display title(s) to apply:", file=sys.stderr)
    for section_id, display_title in titles:
        print(f"  {section_id!r} -> {display_title!r}", file=sys.stderr)

    if args.dry_run:
        print("[dry-run] No changes made.", file=sys.stderr)
        return 0

    sql = """
        INSERT INTO learning.section_display_titles (section_id, display_title, updated_at_utc)
        VALUES (%s, %s, NOW())
        ON CONFLICT (section_id) DO UPDATE
        SET display_title = EXCLUDED.display_title,
            updated_at_utc = NOW()
    """
    with psycopg.connect(dsn) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS learning.section_display_titles (
                    section_id TEXT PRIMARY KEY,
                    display_title TEXT NOT NULL,
                    updated_at_utc TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CHECK (length(trim(section_id)) > 0),
                    CHECK (length(trim(display_title)) > 0)
                )
                """
            )
            for section_id, display_title in titles:
                cur.execute(sql, (section_id, display_title))
        conn.commit()

    print("Done.", file=sys.stderr)
    return 0


def _run_apply_renames(args: argparse.Namespace) -> int:
    """Read a renames YAML and apply each old->new pair that differs."""
    yaml_path = Path(args.yaml)
    if not yaml_path.exists():
        print(f"error: YAML file not found: {yaml_path}", file=sys.stderr)
        return 1

    content = yaml_path.read_text(encoding="utf-8")
    # Parse 'renames:' block — each line: "  old_id: new_id  # optional comment"
    renames: list[tuple[str, str]] = []
    in_renames = False
    entry_re = re.compile(
        r"^\s+([a-zA-Z0-9_. ()-]+?):\s+([a-zA-Z0-9_. ()-]+?)\s*(?:#.*)?$"
    )
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("renames:"):
            in_renames = True
            continue
        if not in_renames:
            continue
        if stripped.startswith("#") or not stripped:
            continue
        m = entry_re.match(line)
        if not m:
            continue
        old_id, new_id = m.group(1).strip(), m.group(2).strip()
        if old_id == new_id:
            continue
        renames.append((old_id, new_id))

    if not renames:
        print("No renames to apply (all identities or file empty).", file=sys.stderr)
        return 0

    dsn = args.dsn or _resolve_dsn()
    psycopg = _require_psycopg()

    print(f"{len(renames)} rename(s) to apply:", file=sys.stderr)
    for old_id, new_id in renames:
        print(f"  {old_id!r} -> {new_id!r}", file=sys.stderr)

    if args.dry_run:
        print("[dry-run] No changes made.", file=sys.stderr)
        return 0

    with psycopg.connect(dsn) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            for old_id, new_id in renames:
                cur.execute(
                    "UPDATE learning.section_title_aliases SET section_id = %s WHERE section_id = %s",
                    (new_id, old_id),
                )
                cur.execute(
                    "UPDATE learning.scan_snapshot_sections SET effective_section_id = %s WHERE effective_section_id = %s",
                    (new_id, old_id),
                )
                cur.execute(
                    "UPDATE learning.scan_snapshot_sections SET raw_section_id = %s WHERE raw_section_id = %s",
                    (new_id, old_id),
                )
        conn.commit()

    print("Done.", file=sys.stderr)
    return 0


def _run_apply(args: argparse.Namespace) -> int:
    yaml_path = Path(args.yaml)
    if not yaml_path.exists():
        print(f"error: YAML file not found: {yaml_path}", file=sys.stderr)
        return 1

    parsed = _parse_candidate_yaml(yaml_path, include_novel=args.include_novel)
    if not parsed:
        print("No aliases found to apply.", file=sys.stderr)
        return 0

    if args.min_section_total > 0:
        section_totals: dict[str, int] = {}
        for _title, section_id, _mode, count in parsed:
            section_totals[section_id] = section_totals.get(section_id, 0) + int(count)

        before = len(parsed)
        parsed = [
            row
            for row in parsed
            if section_totals.get(row[1], 0) >= args.min_section_total
        ]
        after = len(parsed)
        print(
            "Filtered by section total >= "
            f"{args.min_section_total}: kept {after}/{before} aliases",
            file=sys.stderr,
        )

        if not parsed:
            print(
                "No aliases found to apply after section-total filtering.",
                file=sys.stderr,
            )
            return 0

    dsn = args.dsn or _resolve_dsn()

    try:
        upserted = _upsert_aliases(
            dsn,
            parsed,
            source=args.source,
            dry_run=args.dry_run,
            min_count=args.min_count,
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Applied {upserted} aliases from {yaml_path}", file=sys.stderr)

    if args.run_materialize and not args.dry_run:
        return _run_materialize(args)

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    review = sub.add_parser("review", help="Trigger learning_resolve_unknowns.py")
    review_src = review.add_mutually_exclusive_group(required=False)
    review_src.add_argument("--input-json", default=None)
    review_src.add_argument("--dsn", default=None)
    review.add_argument("--min-count", type=int, default=2)
    review.add_argument("--batch-size", type=int, default=100)
    review.add_argument("--rpm", type=int, default=15)
    review.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    review.add_argument("--output-yaml", default="/tmp/candidates.yml")
    review.add_argument("--output-report", default="/tmp/review.md")

    apply_cmd = sub.add_parser(
        "apply", help="Apply YAML aliases to Postgres and optionally rematerialize"
    )
    apply_cmd.add_argument("--yaml", required=True, help="Path to candidates YAML")
    apply_cmd.add_argument("--dsn", default=None)
    apply_cmd.add_argument(
        "--include-novel",
        action="store_true",
        help="Also apply entries from the novel section (default: alias_of only).",
    )
    apply_cmd.add_argument("--source", default="llm_review")
    apply_cmd.add_argument(
        "--min-count",
        type=int,
        default=0,
        help="Only apply aliases with observed count >= this value (default: 0 = all).",
    )
    apply_cmd.add_argument(
        "--min-section-total",
        type=int,
        default=0,
        help=(
            "Apply all aliases for any section_id whose summed candidate count is >= this value "
            "(default: 0 = disabled)."
        ),
    )
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.add_argument(
        "--run-materialize",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Trigger learning_materialize_sections.py --reapply-aliases (default: true).",
    )
    apply_cmd.add_argument("--materialize-batch-size", type=int, default=2000)

    rename_cmd = sub.add_parser(
        "rename-section",
        help="Rename a section_id across all Postgres tables (aliases + materialized rows).",
    )
    rename_cmd.add_argument("--from", dest="old_id", required=True, metavar="OLD_ID")
    rename_cmd.add_argument("--to", dest="new_id", required=True, metavar="NEW_ID")
    rename_cmd.add_argument("--dsn", default=None)
    rename_cmd.add_argument("--dry-run", action="store_true")

    suggest_cmd = sub.add_parser(
        "suggest-canonical",
        help="Show the most popular observed title per section_id (to inform rename decisions).",
    )
    suggest_cmd.add_argument("--dsn", default=None)
    suggest_cmd.add_argument(
        "--min-count",
        type=int,
        default=0,
        metavar="N",
        help="Only show sections with total occurrence count >= N.",
    )
    suggest_cmd.add_argument(
        "--by",
        choices=["raw", "effective"],
        default="raw",
        help="Group by raw_section_id (scanner output, pre-alias) or effective_section_id "
        "(post-alias). Default: raw.",
    )
    suggest_cmd.add_argument(
        "--output-yaml",
        default=None,
        metavar="PATH",
        help="Write suggested renames as a YAML file for use with apply-renames.",
    )

    apply_renames_cmd = sub.add_parser(
        "apply-renames",
        help="Apply a renames YAML produced by suggest-canonical --output-yaml.",
    )
    apply_renames_cmd.add_argument("--yaml", required=True, help="Path to renames YAML")
    apply_renames_cmd.add_argument("--dsn", default=None)
    apply_renames_cmd.add_argument("--dry-run", action="store_true")

    apply_dt_cmd = sub.add_parser(
        "apply-display-titles",
        help="Upsert display titles from a YAML file (keyed by section_id) into Postgres.",
    )
    apply_dt_cmd.add_argument(
        "--yaml",
        required=True,
        help="Path to display_titles YAML (from suggest-canonical --output-yaml)",
    )
    apply_dt_cmd.add_argument("--dsn", default=None)
    apply_dt_cmd.add_argument("--dry-run", action="store_true")

    export_aliases_cmd = sub.add_parser(
        "export-aliases",
        help="Export learned DB aliases to a YAML file in src/ansible_role_doc/data.",
    )
    export_aliases_cmd.add_argument(
        "--output",
        default=str(
            REPO_ROOT / "src/ansible_role_doc/data/section_aliases.learned.yml"
        ),
        help="Output YAML path (default: src/ansible_role_doc/data/section_aliases.learned.yml).",
    )
    export_aliases_cmd.add_argument("--dsn", default=None)
    export_aliases_cmd.add_argument(
        "--min-count",
        type=int,
        default=0,
        help="Only export aliases with metadata.count >= N (default: 0 = all).",
    )
    export_aliases_cmd.add_argument("--dry-run", action="store_true")

    merge_aliases_cmd = sub.add_parser(
        "merge-aliases",
        help="Merge learned aliases YAML into canonical section_aliases YAML.",
    )
    merge_aliases_cmd.add_argument(
        "--base",
        default=str(REPO_ROOT / "src/ansible_role_doc/data/section_aliases.yml"),
        help="Base aliases YAML to merge into.",
    )
    merge_aliases_cmd.add_argument(
        "--learned",
        default=str(
            REPO_ROOT / "src/ansible_role_doc/data/section_aliases.learned.yml"
        ),
        help="Learned aliases YAML to merge from.",
    )
    merge_aliases_cmd.add_argument(
        "--output",
        default=str(REPO_ROOT / "src/ansible_role_doc/data/section_aliases.yml"),
        help="Output merged aliases YAML path.",
    )
    merge_aliases_cmd.add_argument("--dry-run", action="store_true")

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "review":
        return _run_review(args)
    if args.command == "apply":
        return _run_apply(args)
    if args.command == "rename-section":
        return _run_rename_section(args)
    if args.command == "suggest-canonical":
        return _run_suggest_canonical(args)
    if args.command == "apply-renames":
        return _run_apply_renames(args)
    if args.command == "apply-display-titles":
        return _run_apply_display_titles(args)
    if args.command == "export-aliases":
        return _run_export_aliases(args)
    if args.command == "merge-aliases":
        return _run_merge_aliases(args)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
