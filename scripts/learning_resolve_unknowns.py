#!/usr/bin/env python3
"""Classify unknown section titles using an LLM (GitHub Models / OpenAI-compatible API).

Reads unknown section title candidates from either a live database (via the same
DSN resolution as learning_section_title_report.py) or from a JSON file previously
written by ``learning_section_title_report.py --output-json``.

Classifies each candidate as one of:
  alias_of <section_id>   – a synonym for a known section
  group_with <title>      – same meaning as another unknown candidate in the batch
  novel <suggested_id>    – a genuinely new section worth adding
  noise                   – too vague, one-off, or not a real section heading

Outputs ready-to-paste YAML (``--output-yaml``) and/or a markdown review table
(``--output-report``).  Defaults to YAML on stdout if neither flag is given.

Requirements:
  pip install openai
  export GITHUB_TOKEN=<your PAT with models:read>   # for GitHub Models (default)
  # OR
  export OPENAI_API_KEY=<key>                        # for OpenAI directly
  export OPENAI_BASE_URL=https://models.inference.ai.azure.com  # if using GitHub Models
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from learning_app_scaffold import fetch_section_title_report  # noqa: E402
from ansible_role_doc.pattern_config import load_pattern_config  # noqa: E402

# ── GitHub Models defaults ──────────────────────────────────────────────────
_GITHUB_MODELS_BASE_URL = "https://models.inference.ai.azure.com"
_DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# ── Dependency guard ────────────────────────────────────────────────────────


def _require_openai():
    try:
        import openai
    except ImportError as exc:
        raise RuntimeError(
            "openai is required for this script. Install it with: pip install openai"
        ) from exc
    return openai


def _build_client(openai_mod):
    """Return an openai.OpenAI client pointed at GitHub Models or a custom base URL."""
    base_url = os.getenv("OPENAI_BASE_URL", _GITHUB_MODELS_BASE_URL)
    api_key = os.getenv("GITHUB_TOKEN") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "No API key found. Set GITHUB_TOKEN (for GitHub Models) or OPENAI_API_KEY."
        )
    return openai_mod.OpenAI(api_key=api_key, base_url=base_url)


# ── DSN resolution ──────────────────────────────────────────────────────────


def _resolve_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    user = os.getenv("POSTGRES_USER", "learning_user")
    password = os.getenv("POSTGRES_PASSWORD", "learning_pass_change_me")
    db_name = os.getenv("POSTGRES_DB", "learning_scans")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


# ── Prompt construction ─────────────────────────────────────────────────────


def _build_system_prompt(section_aliases: dict[str, str]) -> str:
    # Collect known section IDs and one representative alias each
    id_to_aliases: dict[str, list[str]] = {}
    for alias, section_id in section_aliases.items():
        id_to_aliases.setdefault(section_id, []).append(alias)

    known_sections_lines = []
    for sid in sorted(id_to_aliases):
        sample = id_to_aliases[sid][0]
        known_sections_lines.append(f'  {sid}: e.g. "{sample}"')
    known_sections_block = "\n".join(known_sections_lines)

    return f"""\
You are a taxonomy assistant for Ansible role README headings.

Your task is to classify each normalised section title in the user's JSON list.
For each title, produce exactly one classification:

  alias_of <section_id>   – the title means the same as a known section
  group_with <title>      – the title means the same as another title in this batch
  novel <suggested_id>    – a genuinely new section worth cataloguing (snake_case id)
  noise                   – too vague, one-off junk, or not a real section heading

Known section IDs (and one example alias each):
{known_sections_block}

Respond ONLY with a JSON object where each key is the normalised title (exactly as given)
and each value is one of the strings described above.  No markdown, no extra commentary.

Example response format:
{{
  "build instructions": "alias_of installation",
  "cool stuff": "noise",
  "platform notes": "novel platform_notes",
  "getting started": "group_with quick start"
}}"""


def _build_user_message(titles_with_counts: list[dict[str, Any]]) -> str:
    items = [
        {"title": item["normalized_title"], "count": item["count"]}
        for item in titles_with_counts
    ]
    return json.dumps(items, ensure_ascii=False)


# ── LLM call ────────────────────────────────────────────────────────────────


def _call_llm(
    client, model: str, system_prompt: str, user_message: str
) -> dict[str, str]:
    """Call the LLM and return a dict mapping title → classification string."""

    def _do_call() -> str:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        return response.choices[0].message.content or ""

    raw = _do_call()
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return {str(k): str(v) for k, v in result.items()}
    except json.JSONDecodeError:
        pass

    # Retry once on malformed JSON
    print("  [warn] malformed JSON from LLM, retrying once...", file=sys.stderr)
    raw = _do_call()
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return {str(k): str(v) for k, v in result.items()}
    except json.JSONDecodeError:
        pass

    print("  [warn] second attempt also failed — skipping batch.", file=sys.stderr)
    return {}


# ── Batching loop ────────────────────────────────────────────────────────────


def _run_batches(
    client,
    model: str,
    system_prompt: str,
    candidates: list[dict[str, Any]],
    batch_size: int,
    rpm: int,
) -> dict[str, str]:
    total = len(candidates)
    n_batches = math.ceil(total / batch_size)
    sleep_secs = 60.0 / rpm

    estimate_mins = (n_batches * sleep_secs) / 60.0
    print(
        f"{total} titles → {n_batches} batch{'es' if n_batches != 1 else ''}, "
        f"~{estimate_mins:.1f} min at {rpm} rpm",
        file=sys.stderr,
    )

    all_results: dict[str, str] = {}
    for i in range(n_batches):
        batch = candidates[i * batch_size : (i + 1) * batch_size]
        print(f"Batch {i + 1}/{n_batches} ({len(batch)} titles)...", file=sys.stderr)
        try:
            result = _call_llm(client, model, system_prompt, _build_user_message(batch))
            all_results.update(result)
        except Exception as exc:
            print(
                f"  [error] batch {i + 1} failed: {exc}\n"
                f"  Partial results so far: {len(all_results)} classifications.",
                file=sys.stderr,
            )
            return all_results

        if i < n_batches - 1:
            print(f"  sleeping {sleep_secs:.0f}s...", file=sys.stderr)
            time.sleep(sleep_secs)

    return all_results


# ── Output formatters ────────────────────────────────────────────────────────


def _render_yaml(
    classifications: dict[str, str],
    candidates: list[dict[str, Any]],
) -> str:
    """Render suggested additions grouped by section_id, in section_aliases.yml style."""
    count_map = {item["normalized_title"]: item["count"] for item in candidates}

    # Group alias_of results by target section_id
    alias_groups: dict[str, list[str]] = {}
    novel_entries: list[tuple[str, str, int]] = []  # (suggested_id, title, count)
    noise_entries: list[tuple[str, str, int]] = []
    group_with_entries: list[tuple[str, str, int]] = []

    for title, classification in sorted(classifications.items()):
        parts = classification.split(None, 1)
        tag = parts[0]
        rest = parts[1] if len(parts) > 1 else ""
        cnt = count_map.get(title, 0)

        if tag == "alias_of":
            alias_groups.setdefault(rest, []).append(title)
        elif tag == "novel":
            novel_entries.append((rest, title, cnt))
        elif tag == "noise":
            noise_entries.append((title, cnt))
        elif tag == "group_with":
            group_with_entries.append((title, rest, cnt))

    lines: list[str] = []
    lines.append("# Suggested additions — review and merge into section_aliases.yml")
    lines.append("# Generated by learning_resolve_unknowns.py — human review required")
    lines.append("")
    lines.append("section_aliases:")
    lines.append("")

    if alias_groups:
        lines.append(
            "  # ── alias_of (maps to known sections) ─────────────────────────"
        )
        for section_id in sorted(alias_groups):
            lines.append(
                f"  # ── {section_id} {'─' * max(0, 60 - len(section_id) - 7)}"
            )
            for alias in sorted(alias_groups[section_id]):
                cnt = count_map.get(alias, 0)
                padded = f'"{alias}":'.ljust(54)
                lines.append(f"  {padded} {section_id}  # count={cnt}")
        lines.append("")

    if novel_entries:
        lines.append(
            "  # ── novel (suggested new sections) ────────────────────────────"
        )
        for suggested_id, title, cnt in sorted(novel_entries):
            lines.append(
                f"  # ── {suggested_id} {'─' * max(0, 60 - len(suggested_id) - 7)}"
            )
            padded = f'"{title}":'.ljust(54)
            lines.append(f"  {padded} {suggested_id}  # count={cnt}")
        lines.append("")

    if group_with_entries:
        lines.append(
            "  # ── group_with (LLM grouped unknowns — pick one canonical title)"
        )
        for title, target, cnt in sorted(group_with_entries):
            lines.append(f'  # "{title}" (count={cnt}) → group_with "{target}"')
        lines.append("")

    if noise_entries:
        lines.append(
            "  # ── noise (excluded — too vague or one-off) ───────────────────"
        )
        for title, cnt in sorted(noise_entries):
            lines.append(f'  # "{title}"  # count={cnt}')
        lines.append("")

    return "\n".join(lines)


def _render_report(
    classifications: dict[str, str],
    candidates: list[dict[str, Any]],
) -> str:
    """Render a markdown review table."""
    count_map = {item["normalized_title"]: item["count"] for item in candidates}
    lines: list[str] = []
    lines.append("# Unknown Section Title Classification Report")
    lines.append("")
    lines.append("| Normalized Title | Count | Classification |")
    lines.append("|---|---:|---|")
    for title in sorted(classifications):
        cls = classifications[title]
        cnt = count_map.get(title, "?")
        lines.append(
            f"| {title.replace('|', chr(92) + '|')} | {cnt} | {cls.replace('|', chr(92) + '|')} |"
        )
    lines.append("")
    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)

    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument(
        "--dsn",
        default=None,
        help="PostgreSQL DSN.  Falls back to DATABASE_URL / component env vars.",
    )
    input_group.add_argument(
        "--input-json",
        default=None,
        metavar="PATH",
        help="Path to JSON file previously written by learning_section_title_report.py --output-json.",
    )

    parser.add_argument(
        "--min-count",
        type=int,
        default=2,
        help="Only classify unknown titles seen in at least this many snapshots (default: 2).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of titles to send per API call (default: 100).",
    )
    parser.add_argument(
        "--rpm",
        type=int,
        default=15,
        help="Requests per minute — controls sleep between batches (default: 15).",
    )
    parser.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Model name to use (default: {_DEFAULT_MODEL}, override via OPENAI_MODEL env).",
    )
    parser.add_argument(
        "--output-yaml",
        default=None,
        metavar="PATH",
        help="Write suggested YAML additions to PATH.",
    )
    parser.add_argument(
        "--output-report",
        default=None,
        metavar="PATH",
        help="Write markdown classification review table to PATH.",
    )

    args = parser.parse_args()

    # ── Load report data ──────────────────────────────────────────────────
    if args.input_json:
        json_path = Path(args.input_json)
        if not json_path.exists():
            print(f"error: --input-json path not found: {json_path}", file=sys.stderr)
            return 1
        report = json.loads(json_path.read_text(encoding="utf-8"))
    else:
        dsn = args.dsn or _resolve_dsn()
        report = fetch_section_title_report(dsn)

    # ── Filter candidates ─────────────────────────────────────────────────
    candidates = [
        item
        for item in report.get("unknown_titles", [])
        if int(item["count"]) >= args.min_count
    ]
    if not candidates:
        print(
            f"No unknown titles with count >= {args.min_count}.  Nothing to classify.",
            file=sys.stderr,
        )
        return 0

    # ── Build LLM client and system prompt ────────────────────────────────
    try:
        openai_mod = _require_openai()
        client = _build_client(openai_mod)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    policy = load_pattern_config()
    section_aliases: dict[str, str] = policy.get("section_aliases", {})
    system_prompt = _build_system_prompt(section_aliases)

    # ── Run batched classification ─────────────────────────────────────────
    classifications = _run_batches(
        client,
        model=args.model,
        system_prompt=system_prompt,
        candidates=candidates,
        batch_size=args.batch_size,
        rpm=args.rpm,
    )

    if not classifications:
        print("No classifications returned.", file=sys.stderr)
        return 1

    print(
        f"Classified {len(classifications)}/{len(candidates)} titles.", file=sys.stderr
    )

    # ── Generate outputs ──────────────────────────────────────────────────
    yaml_text = _render_yaml(classifications, candidates)
    report_text = _render_report(classifications, candidates)

    if args.output_yaml:
        out = Path(args.output_yaml)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml_text, encoding="utf-8")
        print(f"Wrote YAML: {out}", file=sys.stderr)

    if args.output_report:
        out = Path(args.output_report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report_text, encoding="utf-8")
        print(f"Wrote report: {out}", file=sys.stderr)

    if not args.output_yaml and not args.output_report:
        try:
            print(yaml_text, end="")
            sys.stdout.flush()
        except BrokenPipeError:
            sys.stdout = open(os.devnull, "w")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
