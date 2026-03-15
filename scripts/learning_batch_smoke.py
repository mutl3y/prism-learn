#!/usr/bin/env python3
"""Run a local learning-loop batch persistence smoke test against Postgres."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from learning_app_scaffold import LearningLoopService
from learning_app_scaffold import PostgresSnapshotStore
from learning_app_scaffold import fetch_recent_batch_summary
from learning_app_scaffold import fetch_recent_failures


def _default_targets(repo_root: Path) -> list[str]:
    return [
        str((repo_root / "src/ansible_role_doc/tests/roles/base_mock_role").resolve()),
        str((repo_root / "missing-role-does-not-exist").resolve()),
    ]


def _resolve_dsn() -> str:
    if os.getenv("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    user = os.getenv("POSTGRES_USER", "learning_user")
    password = os.getenv("POSTGRES_PASSWORD", "learning_pass_change_me")
    db_name = os.getenv("POSTGRES_DB", "learning_scans")
    host = os.getenv("DB_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql://{user}:{password}@{host}:{port}/{db_name}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role-path",
        action="append",
        dest="role_paths",
        help="Role path to scan. Repeat to add multiple targets.",
    )
    parser.add_argument(
        "--run-label",
        default="local-smoke",
        help="Run label persisted in learning.scan_batches.",
    )
    args = parser.parse_args()

    repo_root = REPO_ROOT
    role_paths = args.role_paths or _default_targets(repo_root)

    dsn = _resolve_dsn()
    store = PostgresSnapshotStore(dsn)
    service = LearningLoopService(snapshot_store=store)

    result = service.scan_role_batch(
        role_paths,
        persist_records=True,
        batch_run_label=args.run_label,
        batch_metadata={"invoked_by": "scripts/learning_batch_smoke.py"},
    )

    print("Batch result:")
    print(result.to_dict())

    print("\nRecent batch summary:")
    for row in fetch_recent_batch_summary(dsn, limit=5):
        print(
            f"- id={row['id']} label={row['run_label']} target_type={row['target_type']} "
            f"total={row['total_targets']} succeeded={row['succeeded_targets']} "
            f"failed={row['failed_targets']} failure_rate={row['failure_rate_pct']}%"
        )

    print("\nRecent failures:")
    failures = fetch_recent_failures(dsn, limit=5)
    if not failures:
        print("- none")
    else:
        for row in failures:
            print(
                f"- id={row['id']} target_type={row['target_type']} target={row['target']} "
                f"error={row['error_type']}: {row['error_message']}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
