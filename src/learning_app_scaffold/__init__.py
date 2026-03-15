"""Minimal learning-loop scaffold built on the public ansible_role_doc API."""

from .batching import load_repo_urls, split_fresh_repo_urls
from .service import BatchScanResult, LearningLoopService, ScanFailureRecord
from .service import ScanSnapshot
from .reporting import fetch_fresh_targets, fetch_recent_batch_summary
from .reporting import fetch_recent_failures, fetch_section_title_report
from .storage import PostgresSnapshotStore, SnapshotJsonlStore

__all__ = [
    "BatchScanResult",
    "LearningLoopService",
    "load_repo_urls",
    "PostgresSnapshotStore",
    "ScanFailureRecord",
    "ScanSnapshot",
    "SnapshotJsonlStore",
    "split_fresh_repo_urls",
    "fetch_fresh_targets",
    "fetch_recent_batch_summary",
    "fetch_recent_failures",
    "fetch_section_title_report",
]
