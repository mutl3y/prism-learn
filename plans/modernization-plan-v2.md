# Modernization Plan v2

## Prism-Learn Modernization Program v2 (Active Operating Plan / Source of Truth)

This document is the only active operating plan for prism-learn modernization.

### Active Baseline

- Priority order is strict: correctness first, readability second, reliability/type safety third, performance fourth.
- Breaking changes are allowed when they improve correctness or clarity; each intentional contract delta requires migration/changelog notes.
- TDD is mandatory: each slice starts with focused failing tests before implementation.

### Cross-Repo Coordination (Prism <-> prism-learn)

When Prism rendering contracts change, prism-learn updates are coordinated in the same cycle or blocked.

#### Prism Artifact Contract Matrix (Checklist)

| Prism artifact | Expected contract in prism-learn | Required coordinated regressions |
| --- | --- | --- |
| README markdown | stable required sections and ordering used by downstream parsing and scoring | focused parser/reporting tests + fixture/golden markdown snapshot |
| scanner-report markdown | stable headings and metric labels used by quality/trend reporting | focused reporting tests + fixture/golden scanner-report snapshot |
| runbook markdown | stable action sections and issue-group semantics | focused reporting/tests + fixture/golden runbook snapshot |
| runbook CSV | stable required columns, deterministic order, and value typing expectations | focused CSV contract tests + fixture/golden CSV snapshot |

Coordination rule:

- If Prism changes README/scanner-report/runbook/CSV contracts, prism-learn must add or update focused regression tests before relying on new artifacts.
- Merge is blocked until coordinated focused regressions pass in both repositories.

### Snapshot and Reporting Semantic Invariants

These invariants are mandatory and explicit.

- Current selection invariant: choose latest eligible snapshot in requested scope.
- Previous selection invariant: choose immediately prior snapshot for the same target.
- Ordering invariant: sort by `captured_at_utc` descending, with deterministic `id` tie-break when timestamps match.
- Run-label scoping invariant: run-label/batch filters scope current snapshot selection only.
- Prior lookup invariant under scoping: previous snapshot lookup still resolves same-target history unless comparison is explicitly disabled.
- Determinism invariant: equivalent inputs must produce equivalent selected current/previous snapshots and report metrics.

### Fixture and Golden Test Requirement

For any change touching snapshot selection, scoping, or reporting contracts:

- [ ] add focused failing tests first
- [ ] add or update fixture/golden tests for the invariants above before implementation
- [ ] run focused tests to green
- [ ] update fixture/golden expectations only for intentional contract changes with migration/changelog notes
  - Migration and breaking-change notes go in `plans/changelog.md` under a `## Modernization v2 — Slice <N>` heading.

### Mandatory Acceptance Gates (Every Slice)

- [ ] focused failing tests added first for the slice
- [ ] focused tests pass
- [ ] full tests pass
- [ ] typecheck passes
- [ ] invariant fixture/golden tests pass

### Slice Plan

#### Slice 1: Reporting Contract Consolidation

Scope:

- `src/prism_learn/reporting_common.py`
- `src/prism_learn/reporting.py`
- `src/prism_learn/reporting_quality.py`
- `src/prism_learn/tests/test_prism_learn.py`

#### Slice 2: Batch and Snapshot Selection Clarification

Scope:

- `src/prism_learn/batching.py`
- `src/prism_learn/reporting_batch.py`
- `src/prism_learn/service.py`
- `src/prism_learn/tests/test_prism_learn.py`

#### Slice 3: Reporting Script Contract Alignment

Scope:

- `scripts/learning_refresh_triage_report.py`
- `scripts/learning_doc_quality_report.py`
- `scripts/learning_section_title_report.py`
- `scripts/learning_repo_batch.py`

### Per-Slice Validation Commands

Focused tests first (write failing tests before implementation), then run:

- `.venv/bin/python -m pytest -q src/prism_learn/tests/test_prism_learn.py -k "reporting or quality or batch or snapshot or section_title"`
- `.venv/bin/python -m pytest -q src/prism_learn/tests/test_prism_learn.py -k "golden or fixture or run_label or captured_at_utc"`

Full and type gates:

- `.venv/bin/python -m pytest -q`
- `tox -e typecheck -q`

### Stop-The-Line and Rollback Triggers

- stop immediately if focused failing tests are not written first
- stop immediately if invariant tests are missing for changed semantics
- roll back or isolate the slice if current/previous selection semantics become ambiguous
- roll back or isolate the slice if run-label scoping changes accidentally suppress valid prior same-target history
- roll back or isolate the slice if full tests or typecheck fail and cannot be fixed within the same slice
- **Stop immediately** if scanner-report markdown format changes (section titles, column names, table structure) without a corresponding update to this plan and the prism/prism-learn cross-repo contract matrix.
