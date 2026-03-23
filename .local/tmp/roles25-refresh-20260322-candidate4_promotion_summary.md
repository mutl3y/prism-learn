# Promotion Summary: roles25-refresh-20260322-candidate4

## Decision
PASS - promote `roles25-refresh-20260322-candidate4` over baseline `roles25-refresh-20260322`.

## Evidence
- Doc-quality trend counts:
  - Baseline (`roles25-refresh-20260322_doc_quality.md`): improved=0, regressed=0, stable=25, baseline=0
  - Candidate (`roles25-refresh-20260322-candidate4_doc_quality.md`): improved=5, regressed=0, stable=20, baseline=0
- Scanner unresolved aggregate (parsed from top-rows table in scanner bug list markdown):
  - Baseline (`roles25-refresh-20260322_scanner_bug_list.md`): rows=19, unresolved_sum=345, total_sum=852, ratio=0.4049
  - Candidate (`roles25-refresh-20260322-candidate4_scanner_bug_list.md`): rows=17, unresolved_sum=222, total_sum=766, ratio=0.2898
- Candidate shows lower unresolved burden on compared targets with no regression signal in doc-quality trend counts.

## Validation Tests
- Prism focused tests:
  - `src/prism/tests/test_scanner_internals.py -k "register or set_fact"`: 6 passed
  - `src/prism/tests/test_scan.py -k "when_filters or provenance_issue_categories or referenced_variable_uncertainty_reason"`: 4 passed
  - `src/prism/tests/test_scan.py -k "readme and variable"`: 12 passed
- Prism full suite:
  - `tests: full` task: 617 passed
- Prism-learn section-title focused tests:
  - `src/prism_learn/tests/test_prism_learn.py -k "falls_back_to_stored_sections or aggregates_latest_snapshots"`: 2 passed

## Artifact Paths
- `.local/tmp/roles25-refresh-20260322_scanner_bug_list.md`
- `.local/tmp/roles25-refresh-20260322-candidate4_scanner_bug_list.md`
- `.local/tmp/roles25-refresh-20260322_doc_quality.md`
- `.local/tmp/roles25-refresh-20260322-candidate4_doc_quality.md`
- `.local/tmp/roles25-refresh-20260322-candidate4_promotion_summary.md`
