# Learning App Scaffold

This folder is a minimal scaffold for the future learning-loop orchestration app.

Design constraints:

- It imports only the public `ansible_role_doc.api` surface.
- It does not call CLI entry points.
- It wraps scan results in a persistence-friendly snapshot envelope.

Current scope:

- Local role scans via `LearningLoopService.scan_role(...)`
- Repository scans via `LearningLoopService.scan_repo(...)`
- Batch scans with per-target success/failure capture
- JSONL snapshot persistence via `SnapshotJsonlStore`
- Postgres snapshot/failure persistence via `PostgresSnapshotStore`
- Focused tests proving the scaffold can exercise the public API

Example:

```python
from learning_app_scaffold import LearningLoopService
from learning_app_scaffold import SnapshotJsonlStore

store = SnapshotJsonlStore("scan_snapshots.jsonl")
service = LearningLoopService(snapshot_store=store)
snapshot = service.scan_repo_and_persist(
    "https://github.com/example/role.git",
    repo_style_readme_path="README.md",
)

print(snapshot.to_dict())
```

Each persisted row is an append-only JSON document that includes `schema_version`, target metadata, capture time, and the scanner payload.

Batch example:

```python
from learning_app_scaffold import LearningLoopService
from learning_app_scaffold import SnapshotJsonlStore

service = LearningLoopService(snapshot_store=SnapshotJsonlStore("batch.jsonl"))
result = service.scan_repo_batch(
    [
        "https://github.com/example/role-a.git",
        "https://github.com/example/role-b.git",
    ],
    persist_records=True,
)

print(result.to_dict())
```

Postgres persistence example:

```python
import os

from learning_app_scaffold import LearningLoopService
from learning_app_scaffold import PostgresSnapshotStore

store = PostgresSnapshotStore(os.environ["DATABASE_URL"])
service = LearningLoopService(snapshot_store=store)

batch_id = store.create_batch(
    target_type="repo_url",
    total_targets=2,
    run_label="daily-smoke",
)

result = service.scan_repo_batch(
    [
        "https://github.com/example/role-a.git",
        "https://github.com/example/role-b.git",
    ]
)

for item in result.items:
    store.append(item, batch_id=batch_id)

store.finish_batch(
    batch_id=batch_id,
    succeeded=result.succeeded,
    failed=result.failed,
)
```

When `snapshot_store` is a `PostgresSnapshotStore`, calling `scan_role_batch(..., persist_records=True)` or `scan_repo_batch(..., persist_records=True)` will automatically create and finish a batch row. You can pass optional batch metadata through `batch_run_label=` and `batch_metadata=`.

CLI-style helper for URL lists:

```bash
set -a; . ./.env.podman; set +a
.venv/bin/python scripts/learning_repo_batch.py \
    --repo-url-file scripts/repo_urls.example.txt \
    --repo-style-readme-path README.md \
    --run-label repo-file-smoke
```

Recent-batch summary query:

```python
import os

from learning_app_scaffold import fetch_recent_batch_summary
from learning_app_scaffold import fetch_recent_failures

rows = fetch_recent_batch_summary(os.environ["DATABASE_URL"], limit=20)
for row in rows:
    print(
        row["id"],
        row["target_type"],
        f"failure={row['failure_rate_pct']}%",
        row["started_at_utc"],
    )

failure_rows = fetch_recent_failures(os.environ["DATABASE_URL"], limit=20)
for row in failure_rows:
    print(row["target"], row["error_type"], row["error_message"])
```

Persisted section-title aggregation:

```bash
set -a; . ./.env.podman; set +a
.venv/bin/python scripts/learning_section_title_report.py \
    --run-label sample12-20260315-193723 \
    -o debug_readmes/STYLE_SECTION_TITLE_REPORT.md
```

This report ranks observed known heading variants by canonical section id and lists unknown normalized headings that are good candidates for `section_aliases.yml` updates.
