import importlib.util
from pathlib import Path


def test_learning_resolve_unknowns_imports_with_current_prism_path():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "scripts" / "learning_resolve_unknowns.py"

    spec = importlib.util.spec_from_file_location("learning_resolve_unknowns", script_path)
    assert spec is not None
    assert spec.loader is not None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert hasattr(module, "load_pattern_config")
