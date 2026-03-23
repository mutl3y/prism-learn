# Baseline Promotion Summary

- **Date:** 2026-03-22
- **Gate decision:** PASS

## Previous baseline

- Label: `roles25-refresh-20260322-candidate4`
- Cohort: 25 targets (high-noise targets selected manually)
- Unresolved ratio: 222/766 = 0.2898

## New baseline

- Label: `roles25-refresh-20260322-candidate5`
- Cohort: 50 targets (50 most-recent role targets from DB)
- Batch health: Total: 50 | Succeeded: 50 | Failed: 0 | Failure rate: 0.00%
- Unresolved noise targets above threshold: 0

## Focused tests

```
PYTHONPATH=/raid5/source/test/prism-learn/src \
  .venv/bin/python -m pytest -q src/prism_learn/tests/test_prism_learn.py \
  -k "falls_back_to_stored_sections or aggregates_latest_snapshots"
```

Result: 2/2 passed

## Notes

- Expanded cohort (50 most-recent role targets from DB vs prior 25 high-noise targets); no direct unresolved-ratio comparison available because cohorts differ.
- Zero noise targets above threshold in new cohort and no regressions detected.
- `roles25-refresh-20260322-candidate5` is now the known-good baseline recorded in `.github/agents/prism-learn-agent.md`.
