"""Minimal scaffold for a future learning-loop orchestration app.

The scaffold intentionally depends only on the public ansible_role_doc API so it
can evolve into a separate repository without carrying CLI coupling.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ansible_role_doc import api as scanner_api

if TYPE_CHECKING:
    from .storage import SnapshotJsonlStore


@dataclass(slots=True)
class ScanSnapshot:
    """Normalized payload envelope a learning-loop app can persist."""

    schema_version: int
    target_type: str
    target: str
    captured_at_utc: str
    scan_payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ScanFailureRecord:
    """Normalized failure envelope for batch orchestration flows."""

    schema_version: int
    target_type: str
    target: str
    captured_at_utc: str
    error_type: str
    error_message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BatchScanResult:
    """Summary of a multi-target scan batch."""

    target_type: str
    total: int
    succeeded: int
    failed: int
    items: list[ScanSnapshot | ScanFailureRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "items": [item.to_dict() for item in self.items],
        }


class LearningLoopService:
    """Tiny orchestration-facing facade over the public scanner API."""

    def __init__(
        self,
        api_module=scanner_api,
        snapshot_store: SnapshotJsonlStore | None = None,
    ) -> None:
        self._api = api_module
        self._snapshot_store = snapshot_store

    def scan_role(self, role_path: str, **kwargs: Any) -> ScanSnapshot:
        payload = self._api.scan_role(role_path, **kwargs)
        return self._build_snapshot("role_path", role_path, payload)

    def scan_repo(self, repo_url: str, **kwargs: Any) -> ScanSnapshot:
        payload = self._api.scan_repo(repo_url, **kwargs)
        return self._build_snapshot("repo_url", repo_url, payload)

    def scan_role_and_persist(self, role_path: str, **kwargs: Any) -> ScanSnapshot:
        snapshot = self.scan_role(role_path, **kwargs)
        self.persist_snapshot(snapshot)
        return snapshot

    def scan_repo_and_persist(self, repo_url: str, **kwargs: Any) -> ScanSnapshot:
        snapshot = self.scan_repo(repo_url, **kwargs)
        self.persist_snapshot(snapshot)
        return snapshot

    def persist_snapshot(self, snapshot: ScanSnapshot) -> None:
        if self._snapshot_store is None:
            raise RuntimeError("snapshot store is not configured")
        self._snapshot_store.append(snapshot)

    def persist_record(self, record: ScanSnapshot | ScanFailureRecord) -> None:
        if self._snapshot_store is None:
            raise RuntimeError("snapshot store is not configured")
        self._snapshot_store.append(record)

    def scan_role_batch(
        self,
        role_paths: list[str],
        *,
        persist_records: bool = False,
        batch_run_label: str | None = None,
        batch_metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BatchScanResult:
        return self._scan_batch(
            target_type="role_path",
            targets=role_paths,
            scanner=self.scan_role,
            persist_records=persist_records,
            batch_run_label=batch_run_label,
            batch_metadata=batch_metadata,
            **kwargs,
        )

    def scan_repo_batch(
        self,
        repo_urls: list[str],
        *,
        persist_records: bool = False,
        batch_run_label: str | None = None,
        batch_metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BatchScanResult:
        return self._scan_batch(
            target_type="repo_url",
            targets=repo_urls,
            scanner=self.scan_repo,
            persist_records=persist_records,
            batch_run_label=batch_run_label,
            batch_metadata=batch_metadata,
            **kwargs,
        )

    def _build_snapshot(
        self, target_type: str, target: str, payload: dict[str, Any]
    ) -> ScanSnapshot:
        return ScanSnapshot(
            schema_version=1,
            target_type=target_type,
            target=target,
            captured_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            scan_payload=payload,
        )

    def _build_failure_record(
        self,
        target_type: str,
        target: str,
        error: Exception,
    ) -> ScanFailureRecord:
        return ScanFailureRecord(
            schema_version=1,
            target_type=target_type,
            target=target,
            captured_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            error_type=type(error).__name__,
            error_message=str(error),
        )

    def _scan_batch(
        self,
        *,
        target_type: str,
        targets: list[str],
        scanner,
        persist_records: bool,
        batch_run_label: str | None,
        batch_metadata: dict[str, Any] | None,
        **kwargs: Any,
    ) -> BatchScanResult:
        items: list[ScanSnapshot | ScanFailureRecord] = []
        succeeded = 0
        failed = 0
        batch_id: int | None = None

        if (
            persist_records
            and self._snapshot_store is not None
            and hasattr(self._snapshot_store, "create_batch")
        ):
            batch_id = self._snapshot_store.create_batch(
                target_type=target_type,
                total_targets=len(targets),
                run_label=batch_run_label,
                metadata=batch_metadata,
            )

        for target in targets:
            try:
                record = scanner(target, **kwargs)
                succeeded += 1
            except Exception as exc:
                record = self._build_failure_record(target_type, target, exc)
                failed += 1

            if persist_records:
                self._persist_record(record, batch_id=batch_id)
            items.append(record)

        if (
            persist_records
            and batch_id is not None
            and self._snapshot_store is not None
            and hasattr(self._snapshot_store, "finish_batch")
        ):
            self._snapshot_store.finish_batch(
                batch_id=batch_id,
                succeeded=succeeded,
                failed=failed,
            )

        return BatchScanResult(
            target_type=target_type,
            total=len(targets),
            succeeded=succeeded,
            failed=failed,
            items=items,
        )

    def _persist_record(
        self,
        record: ScanSnapshot | ScanFailureRecord,
        *,
        batch_id: int | None,
    ) -> None:
        if self._snapshot_store is None:
            raise RuntimeError("snapshot store is not configured")

        if batch_id is not None:
            try:
                self._snapshot_store.append(record, batch_id=batch_id)
                return
            except TypeError:
                pass

        self._snapshot_store.append(record)
