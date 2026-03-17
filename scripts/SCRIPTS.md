# Scripts Guide

This folder contains operational scripts for fetching repo targets, running scans,
reporting style-section data, LLM-assisted alias review, and reduced-table
materialization.

## Running Commands

From repo root (`/raid5/source/test/ansible_role_doc`):

```bash
python3 scripts/<script>.py ...
```

From inside this folder (`/raid5/source/test/ansible_role_doc/scripts`):

```bash
python3 <script>.py ...
```

Do not prefix `scripts/` if you are already in `scripts/`.

## Environment

Most DB scripts use this DSN fallback chain:

1. `DATABASE_URL`
2. `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`/`DB_HOST`/`POSTGRES_PORT`

Default DSN if env vars are unset:

```text
postgresql://learning_user:learning_pass_change_me@127.0.0.1:5432/learning_scans
```

LLM scripts use:

- `GITHUB_TOKEN` (preferred for GitHub Models)
- or `OPENAI_API_KEY`
- `OPENAI_BASE_URL` (default: `https://models.inference.ai.azure.com`)
- `OPENAI_MODEL` (default: `gpt-4o-mini`)

## Script Index

### `fetch_galaxy_repo_urls.py`
Fetches role records from Ansible Galaxy API and writes unique GitHub repo URLs.

Examples:

```bash
python3 scripts/fetch_galaxy_repo_urls.py --output scripts/repo_urls.top100k.txt
python3 scripts/fetch_galaxy_repo_urls.py --output /tmp/repo_urls.txt --limit 5000
```

Key options:

- `--output/-o`: output file path
- `--limit/-l`: max URLs to collect (default 100000)
- `--quiet/-q`: suppress progress output

### `learning_repo_batch.py`
Scans repository URLs and persists snapshots/failures in Postgres.

Examples:

```bash
python3 scripts/learning_repo_batch.py --repo-url-file scripts/repo_urls.sample12.txt --run-label repo-batch-sample
python3 scripts/learning_repo_batch.py --repo-url https://github.com/geerlingguy/ansible-role-docker --force-rescan --verbose
```

Key options:

- `--repo-url` (repeatable)
- `--repo-url-file`
- `--skip-if-fresh-days` (default `7`)
- `--force-rescan`
- `--full-scan` (disable README-only lightweight mode)
- `--batch-workers`
- `--run-label`

### `learning_batch_smoke.py`
Small local smoke test (role path targets) against Postgres persistence.

Examples:

```bash
python3 scripts/learning_batch_smoke.py
python3 scripts/learning_batch_smoke.py --role-path src/ansible_role_doc/tests/roles/base_mock_role --run-label local-smoke-custom
```

Key options:

- `--role-path` (repeatable)
- `--run-label`

### `learning_section_title_report.py`
Builds markdown report for section-title usage and unknown heading candidates.

Scale/context:

- Designed for high-volume learning-loop runs; the project has processed about 39k scanned roles across learning batches.
- In a recent reduced snapshot pass, `26,815` latest-per-target rows produced `144,320` aggregated section rows for title analysis.
- Use `--source`, `--all-snapshots`, and min-count filters to tune report shape for your review cadence.

Examples:

```bash
python3 scripts/learning_section_title_report.py -o /tmp/report.md
python3 scripts/learning_section_title_report.py --source raw --output-json /tmp/report.json -o /tmp/report.md
python3 scripts/learning_section_title_report.py --source reduced --min-unknown-count 50 -o /tmp/reduced_report.md
```

Key options:

- `--source {raw,reduced}`
  - `raw`: aggregates from `learning.scan_snapshots.scan_payload`
  - `reduced`: aggregates from `learning.scan_snapshot_sections`
- `--all-snapshots`
- `--batch-id`
- `--run-label`
- `--min-section-count`
- `--min-unknown-count`
- `--output-json`
- `-o/--output`

### `learning_resolve_unknowns.py`
LLM classifier for unknown normalized titles.

Input modes:

- live DB via `--dsn` or env DSN
- offline JSON via `--input-json` from `learning_section_title_report.py --output-json`

Examples:

```bash
python3 scripts/learning_resolve_unknowns.py --input-json /tmp/report.json --min-count 5 --output-yaml /tmp/candidates.yml --output-report /tmp/review.md
python3 scripts/learning_resolve_unknowns.py --dsn "$DATABASE_URL" --batch-size 100 --rpm 15
```

Key options:

- `--min-count`
- `--batch-size`
- `--rpm`
- `--model`
- `--output-yaml`
- `--output-report`

### `learning_materialize_sections.py`
Materializes reduced section rows from raw snapshots into
`learning.scan_snapshot_sections` and applies alias mapping from
`learning.section_title_aliases`.

Examples:

```bash
python3 scripts/learning_materialize_sections.py --batch-size 2000
python3 scripts/learning_materialize_sections.py --reapply-aliases
python3 scripts/learning_materialize_sections.py --full-refresh --reapply-aliases
```

Key options:

- `--batch-size` (default `1000`)
- `--from-snapshot-id`
- `--full-refresh`
- `--reapply-aliases`

Behavior:

- Incremental by default (`MAX(snapshot_id)` already materialized)
- Full refresh truncates and rebuilds the reduced table

### `learning_alias_helper.py`
Workflow helper for LLM review, alias apply/export/merge, display-title updates,
and section-id rename/suggestion utilities.

Subcommands:

- `review`: runs `learning_resolve_unknowns.py`
- `apply`: parses candidates YAML and upserts aliases to Postgres, then optionally rematerializes
- `suggest-canonical`: reports top observed title per section and can write review YAML
- `apply-display-titles`: upserts display-title labels into Postgres lookup table
- `export-aliases`: exports learned DB aliases to YAML in `src/ansible_role_doc/data/`
- `merge-aliases`: merges learned aliases YAML into canonical `section_aliases.yml`
- `rename-section`: bulk section-id rename in Postgres tables
- `apply-renames`: apply batch section-id renames from YAML

Examples:

```bash
python3 scripts/learning_alias_helper.py review --input-json /tmp/report.json --min-count 5 --output-yaml /tmp/candidates.yml --output-report /tmp/review.md
python3 scripts/learning_alias_helper.py apply --yaml /tmp/candidates.yml --dry-run --no-run-materialize
python3 scripts/learning_alias_helper.py apply --yaml /tmp/candidates.yml --min-section-total 85 --min-count 0
python3 scripts/learning_alias_helper.py export-aliases --min-count 1
python3 scripts/learning_alias_helper.py merge-aliases
```

Key `review` options:

- `--input-json` or `--dsn`
- `--min-count`
- `--batch-size`
- `--rpm`
- `--model`
- `--output-yaml`
- `--output-report`

Key `apply` options:

- `--yaml` (required)
- `--include-novel`
- `--min-count N` — title-level threshold
- `--min-section-total N` — section-level threshold (include all aliases in sections whose summed count is >= N)
- `--source` (metadata source label for alias row)
- `--dry-run`
- `--run-materialize/--no-run-materialize`
- `--materialize-batch-size`

Key `suggest-canonical` options:

- `--by {raw,effective}` (default: `raw`)
- `--min-count`
- `--output-yaml`

Key `apply-display-titles` options:

- `--yaml` (required)
- `--dry-run`

Key `export-aliases` options:

- `--output`
- `--min-count`
- `--dry-run`

Key `merge-aliases` options:

- `--base`
- `--learned`
- `--output`
- `--dry-run`

`rename-section` and `apply-renames` are maintenance tools for section-id refactors.
For normal learning-loop updates, prefer `apply` + `export-aliases` + `merge-aliases`.

## Common Workflows

### 1) Generate review candidates from current report

```bash
python3 scripts/learning_section_title_report.py --source reduced --output-json /tmp/report.json
python3 scripts/learning_alias_helper.py review --input-json /tmp/report.json --min-count 5 --output-yaml /tmp/candidates.yml --output-report /tmp/review.md
```

### 2) Preview alias application (section-level threshold)

```bash
python3 scripts/learning_alias_helper.py apply --yaml /tmp/candidates.yml --min-section-total 85 --min-count 0 --dry-run --no-run-materialize
```

### 3) Apply aliases and rematerialize reduced rows

```bash
python3 scripts/learning_alias_helper.py apply --yaml /tmp/candidates.yml --min-section-total 85 --min-count 0
```

### 4) Export learned aliases and merge into app data

```bash
python3 scripts/learning_alias_helper.py export-aliases --min-count 1
python3 scripts/learning_alias_helper.py merge-aliases
```

### 5) Incremental maintenance after new scans

```bash
python3 scripts/learning_materialize_sections.py --reapply-aliases
```

## Input URL Lists

- `scripts/repo_urls.example.txt`
- `scripts/repo_urls.sample12.txt`
- `scripts/repo_urls.top1000.txt`
- `scripts/repo_urls.top100k.txt`

Use these with `learning_repo_batch.py --repo-url-file ...`.
