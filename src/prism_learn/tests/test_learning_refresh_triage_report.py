import importlib.util
from pathlib import Path


def _load_triage_script_module():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "learning_refresh_triage_report.py"
    spec = importlib.util.spec_from_file_location("learning_refresh_triage_report", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fetch_bug_targets_prefers_top_level_role_fields_with_metadata_fallback():
    mod = _load_triage_script_module()

    captured = {"query": "", "params": ()}

    class _FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, query, params):
            captured["query"] = query
            captured["params"] = params

        def fetchall(self):
            return [
                (
                    "https://github.com/example/role-a",
                    "role-a",
                    "Role A",
                    3,
                    10,
                    0.3,
                    1,
                    1,
                    1,
                    0,
                    2,
                )
            ]

    class _FakeConn:
        def cursor(self):
            return _FakeCursor()

    rows = mod._fetch_bug_targets(
        _FakeConn(),
        batch_id=12,
        top_n=5,
        exclude_dummy=True,
        exclude_deprecated=True,
    )

    assert "COALESCE(" in captured["query"]
    assert "s.scan_payload->>'role_name'" in captured["query"]
    assert "s.scan_payload->'metadata'->>'role_name'" in captured["query"]
    assert "s.scan_payload->>'description'" in captured["query"]
    assert "s.scan_payload->'metadata'->>'description'" in captured["query"]
    assert captured["params"] == (12, 5)

    assert len(rows) == 1
    assert rows[0]["target"] == "https://github.com/example/role-a"
    assert rows[0]["role_name"] == "role-a"
    assert rows[0]["description"] == "Role A"
