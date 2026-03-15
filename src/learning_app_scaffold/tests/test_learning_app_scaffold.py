import sys
import types

import pytest

from learning_app_scaffold import LearningLoopService, SnapshotJsonlStore
from learning_app_scaffold import split_fresh_repo_urls
from learning_app_scaffold.reporting import fetch_fresh_targets
from learning_app_scaffold.reporting import fetch_recent_batch_summary
from learning_app_scaffold.reporting import fetch_recent_failures
from learning_app_scaffold.reporting import fetch_section_title_report
from learning_app_scaffold.storage import PostgresSnapshotStore


class _FakeApi:
    def __init__(self):
        self.calls = []

    def scan_role(self, role_path, **kwargs):
        self.calls.append(("scan_role", role_path, kwargs))
        return {"role_name": "mock_role", "metadata": {"scanner_counters": {}}}

    def scan_repo(self, repo_url, **kwargs):
        self.calls.append(("scan_repo", repo_url, kwargs))
        return {"role_name": "demo-role", "metadata": {"scanner_counters": {}}}


class _MixedOutcomeApi(_FakeApi):
    def scan_role(self, role_path, **kwargs):
        self.calls.append(("scan_role", role_path, kwargs))
        if role_path.endswith("broken"):
            raise FileNotFoundError(f"missing role: {role_path}")
        return {"role_name": "mock_role", "metadata": {"scanner_counters": {}}}

    def scan_repo(self, repo_url, **kwargs):
        self.calls.append(("scan_repo", repo_url, kwargs))
        if repo_url.endswith("broken.git"):
            raise RuntimeError(f"clone failed: {repo_url}")
        return {"role_name": "demo-role", "metadata": {"scanner_counters": {}}}


def test_learning_loop_service_scans_role_via_public_api():
    fake_api = _FakeApi()
    service = LearningLoopService(api_module=fake_api)

    snapshot = service.scan_role("/tmp/mock_role", exclude_path_patterns=["tests/**"])

    assert snapshot.target_type == "role_path"
    assert snapshot.target == "/tmp/mock_role"
    assert snapshot.scan_payload["role_name"] == "mock_role"
    assert fake_api.calls == [
        ("scan_role", "/tmp/mock_role", {"exclude_path_patterns": ["tests/**"]})
    ]


def test_learning_loop_service_scans_repo_via_public_api():
    fake_api = _FakeApi()
    service = LearningLoopService(api_module=fake_api)

    snapshot = service.scan_repo(
        "https://github.com/example/demo-role.git",
        repo_role_path="roles/demo",
    )

    assert snapshot.target_type == "repo_url"
    assert snapshot.target == "https://github.com/example/demo-role.git"
    assert snapshot.scan_payload["role_name"] == "demo-role"
    assert fake_api.calls == [
        (
            "scan_repo",
            "https://github.com/example/demo-role.git",
            {"repo_role_path": "roles/demo"},
        )
    ]


def test_scan_snapshot_to_dict_is_persistence_friendly():
    fake_api = _FakeApi()
    service = LearningLoopService(api_module=fake_api)

    snapshot = service.scan_role("/tmp/mock_role")
    payload = snapshot.to_dict()

    assert payload["schema_version"] == 1
    assert payload["target_type"] == "role_path"
    assert payload["target"] == "/tmp/mock_role"
    assert payload["scan_payload"]["role_name"] == "mock_role"
    assert payload["captured_at_utc"].endswith("Z")


def test_learning_loop_service_can_persist_role_snapshot(tmp_path):
    fake_api = _FakeApi()
    store = SnapshotJsonlStore(tmp_path / "snapshots" / "scan.jsonl")
    service = LearningLoopService(api_module=fake_api, snapshot_store=store)

    snapshot = service.scan_role_and_persist("/tmp/mock_role")
    rows = store.read_all()

    assert snapshot.scan_payload["role_name"] == "mock_role"
    assert len(rows) == 1
    assert rows[0]["schema_version"] == 1
    assert rows[0]["target_type"] == "role_path"
    assert rows[0]["target"] == "/tmp/mock_role"


def test_learning_loop_service_can_persist_repo_snapshot(tmp_path):
    fake_api = _FakeApi()
    store = SnapshotJsonlStore(tmp_path / "scan_snapshots.jsonl")
    service = LearningLoopService(api_module=fake_api, snapshot_store=store)

    snapshot = service.scan_repo_and_persist(
        "https://github.com/example/demo-role.git",
        repo_role_path="roles/demo",
    )
    rows = store.read_all()

    assert snapshot.scan_payload["role_name"] == "demo-role"
    assert len(rows) == 1
    assert rows[0]["target_type"] == "repo_url"
    assert rows[0]["target"] == "https://github.com/example/demo-role.git"


def test_persist_snapshot_requires_configured_store():
    fake_api = _FakeApi()
    service = LearningLoopService(api_module=fake_api)
    snapshot = service.scan_role("/tmp/mock_role")

    with pytest.raises(RuntimeError, match="snapshot store is not configured"):
        service.persist_snapshot(snapshot)


def test_learning_loop_service_role_batch_collects_success_and_failure():
    fake_api = _MixedOutcomeApi()
    service = LearningLoopService(api_module=fake_api)

    result = service.scan_role_batch(["/tmp/ok", "/tmp/broken"])

    assert result.target_type == "role_path"
    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert result.items[0].to_dict()["target"] == "/tmp/ok"
    assert result.items[1].to_dict()["error_type"] == "FileNotFoundError"
    assert "missing role" in result.items[1].to_dict()["error_message"]


def test_learning_loop_service_repo_batch_can_persist_all_records(tmp_path):
    fake_api = _MixedOutcomeApi()
    store = SnapshotJsonlStore(tmp_path / "batch.jsonl")
    service = LearningLoopService(api_module=fake_api, snapshot_store=store)

    result = service.scan_repo_batch(
        [
            "https://github.com/example/demo-role.git",
            "https://github.com/example/broken.git",
        ],
        persist_records=True,
    )
    rows = store.read_all()

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert len(rows) == 2
    assert rows[0]["target"] == "https://github.com/example/demo-role.git"
    assert rows[0]["target_type"] == "repo_url"
    assert rows[1]["error_type"] == "RuntimeError"
    assert "clone failed" in rows[1]["error_message"]


def test_persist_record_requires_configured_store():
    fake_api = _MixedOutcomeApi()
    service = LearningLoopService(api_module=fake_api)
    result = service.scan_role_batch(["/tmp/broken"])

    with pytest.raises(RuntimeError, match="snapshot store is not configured"):
        service.persist_record(result.items[0])


def test_batch_persistence_auto_tracks_batch_lifecycle():
    class _FakeBatchStore:
        def __init__(self):
            self.calls = []

        def create_batch(self, **kwargs):
            self.calls.append(("create_batch", kwargs))
            return 99

        def append(self, record, *, batch_id=None):
            self.calls.append(("append", record.to_dict(), batch_id))

        def finish_batch(self, **kwargs):
            self.calls.append(("finish_batch", kwargs))

    fake_api = _MixedOutcomeApi()
    store = _FakeBatchStore()
    service = LearningLoopService(api_module=fake_api, snapshot_store=store)

    result = service.scan_repo_batch(
        [
            "https://github.com/example/demo-role.git",
            "https://github.com/example/broken.git",
        ],
        persist_records=True,
        batch_run_label="nightly",
        batch_metadata={"source": "pytest"},
    )

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1

    assert store.calls[0][0] == "create_batch"
    assert store.calls[0][1]["target_type"] == "repo_url"
    assert store.calls[0][1]["total_targets"] == 2
    assert store.calls[0][1]["run_label"] == "nightly"
    assert store.calls[0][1]["metadata"] == {"source": "pytest"}

    append_calls = [c for c in store.calls if c[0] == "append"]
    assert len(append_calls) == 2
    assert all(c[2] == 99 for c in append_calls)

    assert store.calls[-1][0] == "finish_batch"
    assert store.calls[-1][1] == {"batch_id": 99, "succeeded": 1, "failed": 1}


def test_batch_persistence_without_batch_methods_still_works(tmp_path):
    fake_api = _MixedOutcomeApi()
    store = SnapshotJsonlStore(tmp_path / "batch_without_batch_methods.jsonl")
    service = LearningLoopService(api_module=fake_api, snapshot_store=store)

    result = service.scan_role_batch(["/tmp/ok", "/tmp/broken"], persist_records=True)
    rows = store.read_all()

    assert result.total == 2
    assert result.succeeded == 1
    assert result.failed == 1
    assert len(rows) == 2


def test_postgres_store_inserts_snapshot(monkeypatch):
    calls = []

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            calls.append((query, params))

        def fetchone(self):
            return None

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

        def commit(self):
            pass

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: _FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    store = PostgresSnapshotStore("postgresql://test")
    snapshot = LearningLoopService(api_module=_FakeApi()).scan_role("/tmp/mock_role")
    store.append(snapshot)

    assert calls
    sql, params = calls[0]
    assert "INSERT INTO learning.scan_snapshots" in sql
    assert params[1] == "role_path"
    assert params[2] == "/tmp/mock_role"


def test_postgres_store_inserts_failure(monkeypatch):
    calls = []

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            calls.append((query, params))

        def fetchone(self):
            return None

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

        def commit(self):
            pass

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: _FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    store = PostgresSnapshotStore("postgresql://test")
    result = LearningLoopService(api_module=_MixedOutcomeApi()).scan_role_batch(
        ["/tmp/broken"]
    )
    store.append(result.items[0])

    assert calls
    sql, params = calls[0]
    assert "INSERT INTO learning.scan_failures" in sql
    assert params[1] == "role_path"
    assert params[2] == "/tmp/broken"
    assert params[5] == "FileNotFoundError"


def test_postgres_store_create_and_finish_batch(monkeypatch):
    calls = []

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            calls.append((query, params))

        def fetchone(self):
            return (42,)

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

        def commit(self):
            pass

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: _FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    store = PostgresSnapshotStore("postgresql://test")
    batch_id = store.create_batch(target_type="repo_url", total_targets=2)
    store.finish_batch(batch_id=batch_id, succeeded=1, failed=1)

    assert batch_id == 42
    assert "INSERT INTO learning.scan_batches" in calls[0][0]
    assert "UPDATE learning.scan_batches" in calls[1][0]


def test_postgres_store_raises_when_driver_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)
    store = PostgresSnapshotStore("postgresql://test")
    snapshot = LearningLoopService(api_module=_FakeApi()).scan_role("/tmp/mock_role")

    # Simulate missing driver import for runtime environments without psycopg.
    import builtins

    original_import = builtins.__import__

    def _broken_import(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _broken_import)

    with pytest.raises(RuntimeError, match="psycopg is required"):
        store.append(snapshot)


def test_fetch_recent_batch_summary_returns_rows(monkeypatch):
    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            assert "FROM learning.scan_batches" in query
            assert params == (5,)

        def fetchall(self):
            return [
                (
                    7,
                    "daily-smoke",
                    "repo_url",
                    10,
                    9,
                    1,
                    10.0,
                    "2026-03-15T00:00:00Z",
                    "2026-03-15T00:05:00Z",
                )
            ]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: _FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    rows = fetch_recent_batch_summary("postgresql://test", limit=5)

    assert len(rows) == 1
    assert rows[0]["id"] == 7
    assert rows[0]["failure_rate_pct"] == 10.0


def test_fetch_recent_batch_summary_requires_driver(monkeypatch):
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)

    import builtins

    original_import = builtins.__import__

    def _broken_import(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _broken_import)

    with pytest.raises(RuntimeError, match="psycopg is required"):
        fetch_recent_batch_summary("postgresql://test")


def test_fetch_recent_failures_returns_rows(monkeypatch):
    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            assert "FROM learning.scan_failures" in query
            assert params == (3,)

        def fetchall(self):
            return [
                (
                    11,
                    "role_path",
                    "/tmp/broken",
                    "FileNotFoundError",
                    "missing role",
                    "2026-03-15T00:10:00Z",
                    7,
                )
            ]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: _FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    rows = fetch_recent_failures("postgresql://test", limit=3)
    assert len(rows) == 1
    assert rows[0]["id"] == 11
    assert rows[0]["error_type"] == "FileNotFoundError"


def test_fetch_recent_failures_requires_driver(monkeypatch):
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)

    import builtins

    original_import = builtins.__import__

    def _broken_import(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _broken_import)

    with pytest.raises(RuntimeError, match="psycopg is required"):
        fetch_recent_failures("postgresql://test")


def test_fetch_fresh_targets_returns_latest_matching_rows(monkeypatch):
    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            assert "FROM learning.scan_snapshots AS s" in query
            assert "s.target = ANY(%s)" in query
            assert "NOW() - (%s * INTERVAL '1 day')" in query
            assert params == (
                "repo_url",
                [
                    "https://github.com/example/a",
                    "https://github.com/example/b",
                ],
                7,
            )

        def fetchall(self):
            return [
                (
                    "https://github.com/example/a",
                    "2026-03-15T19:37:31Z",
                    5,
                    "sample12",
                )
            ]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: _FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    rows = fetch_fresh_targets(
        "postgresql://test",
        target_type="repo_url",
        targets=[
            "https://github.com/example/a",
            "https://github.com/example/b",
        ],
        max_age_days=7,
    )

    assert rows == [
        {
            "target": "https://github.com/example/a",
            "captured_at_utc": "2026-03-15T19:37:31Z",
            "batch_id": 5,
            "run_label": "sample12",
        }
    ]


def test_fetch_fresh_targets_short_circuits_without_query(monkeypatch):
    called = False

    def _fail_connect(_dsn):
        nonlocal called
        called = True
        raise AssertionError("database should not be queried")

    fake_psycopg = types.SimpleNamespace(connect=_fail_connect)
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    assert (
        fetch_fresh_targets(
            "postgresql://test",
            target_type="repo_url",
            targets=[],
            max_age_days=7,
        )
        == []
    )
    assert (
        fetch_fresh_targets(
            "postgresql://test",
            target_type="repo_url",
            targets=["https://github.com/example/a"],
            max_age_days=0,
        )
        == []
    )
    assert called is False


def test_split_fresh_repo_urls_skips_recent_targets(monkeypatch):
    monkeypatch.setattr(
        "learning_app_scaffold.batching.fetch_fresh_targets",
        lambda dsn, **kwargs: [
            {
                "target": "https://github.com/example/a",
                "captured_at_utc": "2026-03-15T19:37:31Z",
                "batch_id": 5,
                "run_label": "sample12",
            }
        ],
    )

    repo_urls_to_scan, skipped_recent = split_fresh_repo_urls(
        "postgresql://test",
        [
            "https://github.com/example/a",
            "https://github.com/example/b",
        ],
        skip_if_fresh_days=7,
        force_rescan=False,
    )

    assert repo_urls_to_scan == ["https://github.com/example/b"]
    assert skipped_recent == [
        {
            "target": "https://github.com/example/a",
            "captured_at_utc": "2026-03-15T19:37:31Z",
            "batch_id": 5,
            "run_label": "sample12",
        }
    ]


def test_split_fresh_repo_urls_respects_force_rescan(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("freshness lookup should be bypassed")

    monkeypatch.setattr("learning_app_scaffold.batching.fetch_fresh_targets", _fail)

    repo_urls_to_scan, skipped_recent = split_fresh_repo_urls(
        "postgresql://test",
        ["https://github.com/example/a"],
        skip_if_fresh_days=7,
        force_rescan=True,
    )

    assert repo_urls_to_scan == ["https://github.com/example/a"]
    assert skipped_recent == []


def test_fetch_section_title_report_aggregates_latest_snapshots(monkeypatch):
    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            assert "FROM learning.scan_snapshots AS s" in query
            assert "WHERE ranked.rn = 1" in query
            assert params == ("sample12",)

        def fetchall(self):
            return [
                (
                    "https://github.com/example/a",
                    5,
                    "2026-03-15T19:37:31Z",
                    {
                        "total_sections": 4,
                        "known_sections": 3,
                        "unknown_sections": 1,
                        "by_section_id": {
                            "role_variables": {
                                "count": 2,
                                "titles": ["Role Variables", "Variables"],
                                "normalized_titles": [
                                    "role variables",
                                    "variables",
                                ],
                            },
                            "example_usage": {
                                "count": 1,
                                "titles": ["Example Playbook"],
                                "normalized_titles": ["example playbook"],
                            },
                            "unknown": {
                                "count": 1,
                                "titles": ["Supported platforms"],
                                "normalized_titles": ["supported platforms"],
                            },
                        },
                    },
                    None,
                ),
                (
                    "https://github.com/example/b",
                    5,
                    "2026-03-15T19:37:32Z",
                    {
                        "total_sections": 3,
                        "known_sections": 2,
                        "unknown_sections": 1,
                        "by_section_id": {
                            "role_variables": {
                                "count": 1,
                                "titles": ["Variables"],
                                "normalized_titles": ["variables"],
                            },
                            "requirements": {
                                "count": 1,
                                "titles": ["Requirements"],
                                "normalized_titles": ["requirements"],
                            },
                            "unknown": {
                                "count": 1,
                                "titles": ["Supported platforms"],
                                "normalized_titles": ["supported platforms"],
                            },
                        },
                    },
                    None,
                ),
            ]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: _FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    report = fetch_section_title_report(
        "postgresql://test",
        run_label="sample12",
        latest_per_target=True,
    )

    assert report["snapshot_count"] == 2
    assert report["distinct_targets"] == 2
    assert report["total_sections"] == 7
    assert report["known_sections"] == 5
    assert report["unknown_sections"] == 2
    assert report["sections"][0]["section_id"] == "role_variables"
    assert report["sections"][0]["count"] == 3
    assert report["sections"][0]["titles"][0] == {"title": "Variables", "count": 2}
    assert report["unknown_titles"] == [
        {
            "normalized_title": "supported platforms",
            "count": 2,
            "distinct_targets": 2,
            "sample_targets": [
                "https://github.com/example/a",
                "https://github.com/example/b",
            ],
            "batch_ids": [5],
            "latest_seen_at": "2026-03-15T19:37:32Z",
            "titles": [{"title": "Supported platforms", "count": 2}],
        }
    ]


def test_fetch_section_title_report_supports_all_snapshots_and_string_json(monkeypatch):
    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            assert "WHERE ranked.rn = 1" not in query
            assert params == ()

        def fetchall(self):
            return [
                (
                    "https://github.com/example/a",
                    None,
                    "2026-03-15T19:37:31Z",
                    '{"total_sections": 1, "known_sections": 1, "unknown_sections": 0, "by_section_id": {"requirements": {"count": 1, "titles": ["Requirements"], "normalized_titles": ["requirements"]}}}',
                    None,
                )
            ]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: _FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    report = fetch_section_title_report(
        "postgresql://test",
        latest_per_target=False,
    )

    assert report["snapshot_count"] == 1
    assert report["sections"] == [
        {
            "section_id": "requirements",
            "known": True,
            "count": 1,
            "snapshot_count": 1,
            "distinct_targets": 1,
            "sample_targets": ["https://github.com/example/a"],
            "titles": [{"title": "Requirements", "count": 1}],
            "normalized_titles": [{"title": "requirements", "count": 1}],
        }
    ]
    assert report["unknown_titles"] == []


def test_fetch_section_title_report_falls_back_to_stored_sections(monkeypatch):
    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            assert params == ()

        def fetchall(self):
            return [
                (
                    "https://github.com/example/a",
                    5,
                    "2026-03-15T19:37:31Z",
                    None,
                    [
                        {"id": "role_variables", "title": "Role Variables"},
                        {"id": "unknown", "title": "Supported platforms"},
                    ],
                )
            ]

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return _FakeCursor()

    fake_psycopg = types.SimpleNamespace(connect=lambda dsn: _FakeConn())
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    report = fetch_section_title_report("postgresql://test")

    assert report["total_sections"] == 2
    assert report["known_sections"] == 1
    assert report["unknown_sections"] == 1
    assert report["sections"][0]["section_id"] == "role_variables"
    assert report["unknown_titles"][0]["normalized_title"] == "supported platforms"


def test_fetch_section_title_report_requires_driver(monkeypatch):
    monkeypatch.delitem(sys.modules, "psycopg", raising=False)

    import builtins

    original_import = builtins.__import__

    def _broken_import(name, *args, **kwargs):
        if name == "psycopg":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _broken_import)

    with pytest.raises(RuntimeError, match="psycopg is required"):
        fetch_section_title_report("postgresql://test")
