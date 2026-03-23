# roles25-refresh-20260322-candidate8 Promotion Summary

- Date: 2026-03-22
- Previous baseline: roles25-refresh-20260322-candidate4 (25 targets, 222/796=0.2789 unresolved ratio)
- New baseline: roles25-refresh-20260322-candidate8 (25 targets, 218/792=0.2753 unresolved ratio)
- Improvement: -4 unresolved, ratio -0.0036
- Gate decision: PASS
- Focused tests: 2/2 passed
- Pytest invocation: `cd /raid5/source/test/prism && PYTHONPATH=src .venv/bin/python -m pytest -q src/prism/tests/test_scan.py src/prism/tests/test_scanner_internals.py`

## Lanes Applied

- A: Added 9 Jinja2 globals/loop vars to `ignored_identifiers.yml` (`cycler`, `dict`, `joiner`, `lipsum`, `loop`, `namespace`, `now`, `range`, `undef`)
- B: Added `vars` to `scan_dirs` in `_collect_referenced_variable_names`
- C: Added `_REGISTERED_RESULT_ATTRS` filter (`stdout`, `stderr`, `rc`, etc.) in `_collect_referenced_variable_names`
- D: Attempted README code-fence extraction - REVERTED (caused regression: +49 unresolved)
- E: Added uppercase-name detection to `_build_referenced_variable_uncertainty_reason`

## Notes

- Modest improvement (-0.36pp unresolved ratio).
- Lane D reverted.
- Modest gains from A/C on bind (-1) and nginx (-1).
