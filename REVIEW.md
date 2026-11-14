# Second-pass implementation review

## Findings fixed locally

1. **High: completed exports were reused across newly validated runs.** The export
   directory was keyed only by query, so repeating the same search later returned
   the old completed result set. It is now keyed by query and validation manifest;
   resumability remains scoped to the same report.
2. **High: failed report refresh left the earlier delivery current.** A successful
   manifest remained available to export after subsequent live validation failed.
   Report now archives and revokes the previous manifest before starting a new
   validation attempt. Failed attempts cannot retain current delivery status.
3. **High: revision critiques could omit previous findings.** Only closing and
   verification rounds checked prior finding IDs. All rounds now retain and require
   dispositions for previous findings.
4. **Medium: critique budgets were lifetime workspace limits.** A completed run's
   rounds consumed the next update's budget. New post-delivery cycles have their
   own depth-based budget, retaining global packet numbering and prior findings.
5. **Medium: diagnostic reporting raised instead of reporting blockers.**
   `report --diagnostic` now returns structured blockers without generating a
   validated delivery or revoking an existing report.

Each finding has a regression test in tests/test_recheck.py.
The 2026-11-14 follow-up corrected the scoped search operator to `has` and the
work-ID filter to `ids.openalex`. Direct API checks also exposed a proximity
validation error with redundant parentheses. On Windows, text-mode newline
conversion caused freshly written report files to fail their integrity check.
Atomic writes now use UTF-8 with LF so the manifest hashes match the file bytes.

## Remaining verification limits

- The [verification log](IMPLEMENTATION_STATUS.md) records the live contracts
  exercised. Compound proximity in one scoped search leaf returned HTTP 500 from
  validation. Explicit native OQL proximity passed replay checks and changed
  the result count for the tested query. Fresh validation remains required.
- Multidisciplinary fixtures are synthetic plumbing tests, not real screened
  review benchmarks. A separate [screened-review pilot](evals/screened-pilot/README.md) records
  the first observed relative recall and its denominator limitations.
- Role separation and mining commands protect current held-out sets, but the
  agent must still disclose earlier exposure when establishing holdouts. The
  workspace does not prove a record has never been seen outside the tool.
- This adaptation rewrites much of the original engine. Its offline tests do not
  establish behavioral parity with every upstream workflow safeguard.
