prism-learn
==========

Batch learning infrastructure for [prism](https://github.com/mutl3y/prism): Postgres-backed role scanning, snapshot storage, and analysis reporting.

This package depends on `prism-ansible` for the core role scanner and provides:

- `learning_app_scaffold` — batch orchestration, Postgres snapshot store, and reporting modules
- `scripts/` — CLI batch runners for scanning Galaxy role repositories
- `infra/` — Postgres init SQL and Podman container configuration

## Installation

```bash
pip install prism-learn
```

This will also install `prism-ansible` as a dependency.

## Infrastructure

Start the local Postgres instance:

```bash
podman-compose up -d
```

## Usage

```bash
# Batch scan a list of role repo URLs
python scripts/learning_repo_batch.py --repo-urls scripts/repo_urls.sample12.txt

# Quality report
python scripts/learning_doc_quality_report.py

# Section title report
python scripts/learning_section_title_report.py
```

## Development

```bash
pip install -e .[dev]
tox
```
