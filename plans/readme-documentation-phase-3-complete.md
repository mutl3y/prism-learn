## Phase 3 Complete: Usage Guide and Workflow Documentation

Successfully added comprehensive usage examples, workflow documentation, and finishing sections to README.md. The documentation now provides complete guidance from introduction through practical examples to contribution guidelines, creating a polished, production-ready README.

**Files created/changed:**
- README.md

**Functions created/changed:**
- N/A (documentation)

**Tests created/changed:**
- N/A (documentation)

**Review Status:** APPROVED

**Git Commit Message:**
```
docs: Add usage examples and workflow documentation to README

- Add "How It Works" section explaining four-stage cycle
- Include Mermaid sequence diagram showing agent interaction flow
- Add realistic usage example demonstrating JWT authentication implementation
- Document generated artifacts (plan files, phase completions, final completion)
- Add tips and best practices for working with the Orchestra
- Include "Extending the Orchestra" section for customization
- Add contributing guidelines and MIT license
- Complete comprehensive, production-ready README
```

## Scan Data Retention Guardrails (2026-03-25)

To keep baseline/candidate comparisons reproducible and to reduce accidental data loss, use these operational guardrails for all scan/report cycles.

### 1) Run label discipline

- Always include a date token in run labels, for example: `roles25-refresh-20260322-candidate8-rebuild-20260325`.
- Use one consistent prefix per run across generated artifacts (`--prefix` should match `--run-label`).
- Never reuse labels for materially different cohorts.

### 2) Cohort reproducibility

- Treat the cohort URL file as a first-class artifact and store it in `.local/tmp/<label>_urls.txt`.
- For comparable same-day baseline/candidate runs, rebuild from the exact target set captured in `learning.scan_snapshots` for the reference batch.
- Prefer deriving cohort targets from DB batch snapshots over ad hoc lists when validating parity.

### 3) Freshness bypass for comparability

- `scripts/learning_repo_batch.py` defaults to freshness skipping (`--skip-if-fresh-days 7`).
- For same-day comparisons, always use `--force-rescan` (or `--skip-if-fresh-days 0`) to avoid hidden no-op targets.

### 4) Artifact retention and preservation

- Generate and retain at minimum these files under `.local/tmp/` for each promoted run label:
- Required artifact: `.local/tmp/<label>_bug_targets.tsv`
- Required artifact: `.local/tmp/<label>_scanner_bug_list.md`
- Required artifact: `.local/tmp/<label>_doc_quality.json`
- Required artifact: `.local/tmp/<label>_doc_quality.md`
- Preserve known-good baseline artifacts (currently `roles25-refresh-20260322-candidate8`) when pruning old temp files.
- If storage cleanup is required, remove only stale transient files and explicitly exempt active baseline/candidate labels.

### 5) Verification SQL before decisioning

Run these checks before promoting a candidate:

```sql
-- latest batch counters for two labels
WITH labels AS (
  SELECT unnest(ARRAY[
    'BASELINE_LABEL',
    'CANDIDATE_LABEL'
  ]) AS run_label
), latest AS (
  SELECT l.run_label, b.id AS batch_id, b.total_targets, b.succeeded_targets, b.failed_targets
  FROM labels l
  JOIN LATERAL (
    SELECT id, total_targets, succeeded_targets, failed_targets
    FROM learning.scan_batches
    WHERE run_label = l.run_label
    ORDER BY id DESC
    LIMIT 1
  ) b ON TRUE
)
SELECT * FROM latest ORDER BY run_label;

-- set parity check using snapshots joined by batch_id
WITH baseline AS (
  SELECT DISTINCT s.target
  FROM learning.scan_snapshots s
  JOIN learning.scan_batches b ON b.id = s.batch_id
  WHERE b.run_label = 'BASELINE_LABEL'
    AND s.target_type = 'repo_url'
), candidate AS (
  SELECT DISTINCT s.target
  FROM learning.scan_snapshots s
  JOIN learning.scan_batches b ON b.id = s.batch_id
  WHERE b.run_label = 'CANDIDATE_LABEL'
    AND s.target_type = 'repo_url'
)
SELECT 'baseline_minus_candidate' AS diff_set, COUNT(*)
FROM (SELECT target FROM baseline EXCEPT SELECT target FROM candidate) d
UNION ALL
SELECT 'candidate_minus_baseline' AS diff_set, COUNT(*)
FROM (SELECT target FROM candidate EXCEPT SELECT target FROM baseline) d;
```

### 6) Operational checklist

- Build/confirm cohort URL file.
- Run refresh with forced rescan for comparable cycles.
- Generate scanner triage and doc-quality outputs for both labels.
- Validate batch totals, success rates, and target-set parity.
- Record decision and keep baseline artifacts for next cycle.
