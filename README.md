prism-learn
==========

<!-- Codespaces badge disabled for now.
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/mutl3y/prism-learn)
-->

Batch learning infrastructure for [prism](https://github.com/mutl3y/prism): Postgres-backed role scanning, snapshot storage, and analysis reporting.

This package depends on `prism-ansible` for the core role scanner and provides:

- `prism_learn` — batch orchestration, Postgres snapshot store, and reporting modules
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

### Concurrent scanning example

`learning_repo_batch.py` supports concurrent repository scans through the
service batch runner.

- Use `--batch-workers` to set explicit concurrency.
- Omit `--batch-workers` to use the default IO-oriented fan-out.
	The service computes this as `min(target_count, max(8, cpu_count * 8))`.

```bash
# Scan with explicit concurrency (6 worker threads), verbose progress,
# and full (non-lightweight) scan mode.
python scripts/learning_repo_batch.py \
	--repo-url-file scripts/repo_urls.sample12.txt \
	--batch-workers 6 \
	--verbose \
	--full-scan \
	--run-label concurrency-demo
```

```bash
# Use default concurrency and skip recently scanned repos (default: 7 days).
python scripts/learning_repo_batch.py \
	--repo-url-file scripts/repo_urls.sample12.txt \
	--run-label default-concurrency-demo
```

```bash
# Force rescanning all provided repos regardless of freshness window.
python scripts/learning_repo_batch.py \
	--repo-url-file scripts/repo_urls.sample12.txt \
	--force-rescan \
	--run-label forced-concurrency-demo
```

## Development

```bash
make dev
tox -e lint
tox -e pre-commit
tox
```

`make dev` creates `.venv`, installs editable dev dependencies, and installs
local pre-commit hooks.

<!--
## Codespaces (disabled for now)

This repository includes `.devcontainer/devcontainer.json` so you can open it
directly in GitHub Codespaces.

After the Codespace is created, dependencies are installed automatically with:

```bash
python3 -m pip install -e .[dev]
```

Common checks in Codespaces:

```bash
tox -e lint
tox -e pre-commit
tox
```
-->
