#!/usr/bin/env python3
"""Run a repository URL batch scan and persist results to Postgres."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import threading
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from learning_app_scaffold import LearningLoopService  # noqa: E402
from learning_app_scaffold import PostgresSnapshotStore  # noqa: E402
from learning_app_scaffold import fetch_recent_batch_summary  # noqa: E402
from learning_app_scaffold import fetch_recent_failures  # noqa: E402
from learning_app_scaffold import load_repo_urls  # noqa: E402
from learning_app_scaffold import split_fresh_repo_urls  # noqa: E402


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
        "--repo-url",
        action="append",
        default=[],
        help="Repository URL to scan. Repeat to add multiple targets.",
    )
    parser.add_argument(
        "--repo-url-file",
        default=None,
        help="Text file with one repository URL per line (blank lines and # comments are ignored).",
    )
    parser.add_argument(
        "--repo-role-path",
        default=".",
        help="Role path inside each cloned repo (default: .).",
    )
    parser.add_argument(
        "--repo-style-readme-path",
        default="README.md",
        help="README path inside each repo used as style source.",
    )
    parser.add_argument(
        "--run-label",
        default="repo-batch",
        help="Run label persisted in learning.scan_batches.",
    )
    parser.add_argument(
        "--recent-limit",
        type=int,
        default=10,
        help="How many recent batch/failure rows to print.",
    )
    parser.add_argument(
        "--skip-if-fresh-days",
        type=int,
        default=7,
        help=(
            "Skip repository URLs whose latest persisted snapshot is newer than this many days "
            "(default: 7). Set to 0 to disable freshness skipping."
        ),
    )
    parser.add_argument(
        "--force-rescan",
        action="store_true",
        help="Ignore freshness skipping and rescan all provided repository URLs.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-repository progress while processing the batch.",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Disable lightweight README-only mode and run full repository scans.",
    )
    parser.add_argument(
        "--batch-workers",
        type=int,
        default=None,
        help="Optional worker override for service-level batch fan-out.",
    )
    args = parser.parse_args()

    repo_urls = load_repo_urls(args.repo_url, args.repo_url_file)
    if not repo_urls:
        raise SystemExit(
            "No repository URLs were provided. Use --repo-url and/or --repo-url-file."
        )

    dsn = _resolve_dsn()
    repo_urls_to_scan, skipped_recent = split_fresh_repo_urls(
        dsn,
        repo_urls,
        skip_if_fresh_days=args.skip_if_fresh_days,
        force_rescan=args.force_rescan,
    )

    if skipped_recent:
        print("Skipping recently scanned repos:")
        for row in skipped_recent:
            print(
                f"- {row['target']} (latest={row['captured_at_utc']}, run_label={row['run_label'] or 'n/a'})"
            )
        print()

    store = PostgresSnapshotStore(dsn)
    service = LearningLoopService(snapshot_store=store)

    if args.verbose:
        total_targets = len(repo_urls_to_scan)
        original_scan_repo = service.scan_repo
        progress = {"index": 0}
        progress_lock = threading.Lock()

        def scan_repo_with_progress(repo_url: str, **kwargs):
            with progress_lock:
                progress["index"] += 1
                index = progress["index"]
            print(f"[{index}/{total_targets}] Scanning: {repo_url}")
            try:
                snapshot = original_scan_repo(repo_url, **kwargs)
            except Exception as exc:
                print(
                    f"[{index}/{total_targets}] Failed: {repo_url} "
                    f"({type(exc).__name__}: {exc})"
                )
                raise
            print(f"[{index}/{total_targets}] Done: {repo_url}")
            return snapshot

        service.scan_repo = scan_repo_with_progress

    if not repo_urls_to_scan:
        print(
            "All repository URLs were skipped because their latest persisted scan is within "
            f"{args.skip_if_fresh_days} days."
        )
        print("\nRecent batch summary:")
        for row in fetch_recent_batch_summary(dsn, limit=args.recent_limit):
            print(
                f"- id={row['id']} label={row['run_label']} target_type={row['target_type']} "
                f"total={row['total_targets']} succeeded={row['succeeded_targets']} "
                f"failed={row['failed_targets']} failure_rate={row['failure_rate_pct']}%"
            )

        print("\nRecent failures:")
        failures = fetch_recent_failures(dsn, limit=args.recent_limit)
        if not failures:
            print("- none")
        else:
            for row in failures:
                print(
                    f"- id={row['id']} target_type={row['target_type']} target={row['target']} "
                    f"error={row['error_type']}: {row['error_message']}"
                )
        return 0

    try:
        result = service.scan_repo_batch(
            repo_urls_to_scan,
            persist_records=True,
            batch_max_workers=args.batch_workers,
            batch_run_label=args.run_label,
            batch_metadata={
                "invoked_by": "scripts/learning_repo_batch.py",
                "repo_role_path": args.repo_role_path,
                "repo_style_readme_path": args.repo_style_readme_path,
                "lightweight_readme_only": not args.full_scan,
                "batch_max_workers": args.batch_workers,
                "target_count": len(repo_urls_to_scan),
                "requested_target_count": len(repo_urls),
                "skipped_recent_target_count": len(skipped_recent),
                "skip_if_fresh_days": args.skip_if_fresh_days,
                "force_rescan": args.force_rescan,
            },
            repo_role_path=args.repo_role_path,
            repo_style_readme_path=args.repo_style_readme_path,
            lightweight_readme_only=not args.full_scan,
        )
    except KeyboardInterrupt:
        print("Interrupted by user (Ctrl+C).")
        return 130

    print("Batch result:")
    print(result.to_dict())

    print("\nRecent batch summary:")
    for row in fetch_recent_batch_summary(dsn, limit=args.recent_limit):
        print(
            f"- id={row['id']} label={row['run_label']} target_type={row['target_type']} "
            f"total={row['total_targets']} succeeded={row['succeeded_targets']} "
            f"failed={row['failed_targets']} failure_rate={row['failure_rate_pct']}%"
        )

    print("\nRecent failures:")
    failures = fetch_recent_failures(dsn, limit=args.recent_limit)
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
