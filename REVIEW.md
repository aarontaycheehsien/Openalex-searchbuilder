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
Verification: 35 offline tests passed; 1 live test skipped (no key).

## Remaining verification limits

- The OpenAlex query, field, identifier, and paging contracts have not been tested
  against the live service. Local transport mocks and the fake corpus do not prove
  current API compatibility or reproduce OpenAlex linguistic semantics.
- Multidisciplinary fixtures are synthetic plumbing tests, not real screened
  review benchmarks. Empirical search effectiveness remains unevaluated.
- Role separation and mining commands protect current held-out sets, but the
  agent must still disclose earlier exposure when establishing holdouts. The
  workspace does not prove a record has never been seen outside the tool.
- This adaptation rewrites much of the original engine. Its offline tests do not
  establish behavioral parity with every upstream workflow safeguard.
