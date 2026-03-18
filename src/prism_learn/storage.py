"""Persistence helpers for the learning-loop scaffold."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class _SnapshotLike(Protocol):
    def to_dict(self) -> dict: ...


class SnapshotJsonlStore:
    """Append-only JSONL store for scan snapshots.

    This is intentionally simple and file-based so the learning-loop scaffold can
    persist snapshots immediately without committing to a database backend.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, snapshot: _SnapshotLike) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(snapshot.to_dict(), sort_keys=True))
            handle.write("\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows: list[dict] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows


class PostgresSnapshotStore:
    """Postgres persistence adapter for learning-loop snapshots and failures.

    The expected schema is provisioned by `infra/postgres/init/010_learning_schema.sql`.
    This adapter keeps write behavior intentionally small and append-oriented.
    """

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def append(self, record: _SnapshotLike, *, batch_id: int | None = None) -> None:
        payload = record.to_dict()
        if "error_type" in payload:
            self._insert_failure(payload, batch_id=batch_id)
            return
        self._insert_snapshot(payload, batch_id=batch_id)

    def create_batch(
        self,
        *,
        target_type: str,
        total_targets: int,
        run_label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        metadata_payload = metadata or {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO learning.scan_batches (
                        target_type,
                        run_label,
                        total_targets,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (
                        target_type,
                        run_label,
                        total_targets,
                        json.dumps(metadata_payload, sort_keys=True),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        if not row:
            raise RuntimeError("failed to create scan batch")
        return int(row[0])

    def finish_batch(self, *, batch_id: int, succeeded: int, failed: int) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE learning.scan_batches
                    SET succeeded_targets = %s,
                        failed_targets = %s,
                        finished_at_utc = NOW()
                    WHERE id = %s
                    """,
                    (succeeded, failed, batch_id),
                )
            conn.commit()

    def _insert_snapshot(
        self, payload: dict[str, Any], *, batch_id: int | None
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO learning.scan_snapshots (
                        schema_version,
                        target_type,
                        target,
                        captured_at_utc,
                        batch_id,
                        scan_payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        payload["schema_version"],
                        payload["target_type"],
                        payload["target"],
                        payload["captured_at_utc"],
                        batch_id,
                        json.dumps(payload["scan_payload"], sort_keys=True),
                    ),
                )
            conn.commit()

    def _insert_failure(self, payload: dict[str, Any], *, batch_id: int | None) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO learning.scan_failures (
                        schema_version,
                        target_type,
                        target,
                        captured_at_utc,
                        batch_id,
                        error_type,
                        error_message
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        payload["schema_version"],
                        payload["target_type"],
                        payload["target"],
                        payload["captured_at_utc"],
                        batch_id,
                        payload["error_type"],
                        payload["error_message"],
                    ),
                )
            conn.commit()

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required for PostgresSnapshotStore. Install it with `pip install psycopg[binary]`."
            ) from exc
        return psycopg.connect(self.dsn)
