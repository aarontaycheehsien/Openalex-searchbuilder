# Evaluation fixtures

`development.json` and `heldout.json` are **synthetic multidisciplinary contract
fixtures**, not gold-standard reviews or claims about real recall. IDs and titles
are synthetic and must never be sent to OpenAlex as known papers. The development
set covers urban climate and education; the held-out set covers economics and
clinical research. `tests/test_evals.py` evaluates these sets separately.

The tiny fake evaluator tests plumbing, corpus/field selection and set membership.
It does not reproduce OpenAlex stemming, keyword classification or relevance.

For empirical evaluation, establish independently screened real records and
resolve their identifiers, freeze development/held-out topic manifests before
iteration, run each topic at least three times, and report per-set relative recall,
unseen recall and corpus coverage separately. Keep unsuccessful attempts. If a
held-out topic informs a change, retire it from independent evaluation. Do not
substitute synthetic-fixture scores for this process.

Live integration tests are opt-in and separate from effectiveness evaluation. No
live or empirical search performance results are claimed by this release.
