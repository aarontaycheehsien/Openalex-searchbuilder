# Screened-review pilot, 2026-11-14

The frozen title/abstract strategies retrieved 17 of 17 identifiable works in the
development topic and 19 of 39 in the held-out topic. Both evaluable topics gave
identical counts and retrieved IDs across three fresh API runs in the same session.
The repetitions check short-term repeatability. They share the same relevance judgments.

| Topic | Role | Included source rows | Rows resolved by DOI | Distinct resolved works in all corpora | Retrieved works | Relative recall | Total query hits |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Wilson disease therapies | Development | 29 | 20 | 17/17 | 17 | 100% | 14,861 |
| Nudging healthcare professionals | Original held-out | 101 | 0 | — | — | Unevaluable | — |
| Cognitive behavioral therapy for anxiety-related disorders | Replacement held-out | 73 | 39 | 39/39 | 19 | 48.7% | 36,897 |

Relative recall divides retrieved distinct works by resolved distinct works present
in the selected corpus. The 20 resolved Wilson disease rows mapped to 17 unique
IDs. All DOI-bearing rows resolved in both evaluable topics. The unlinked rows
remain unknown; the pilot cannot estimate recall for all review inclusions or
precision across the full result sets.

## Design and reproduction

We selected topics and vocabulary from review-level descriptions. We froze the
queries and final-inclusion rule in commit `071ef98` before lookup and did not
inspect included titles or abstracts to tune vocabulary. The first held-out CSV
lacked the DOI column, and the first runner stopped at that column lookup. We
retained the original topic with zero identifiable works, preserved the completed
development run, and froze the replacement query in `0ec45ce` before running it.
No searches were tuned after observing outcomes. Future tuning on the released
held-out results must use another topic for independent testing.

The runner selects every source row with `label_included=1`, resolves available
DOIs with the repository client, deduplicates by OpenAlex ID, then measures corpus
membership and query retrieval by API intersection. All queries use the all-corpora
setting and stemmed title/abstract search. The benchmark measures the frozen
queries; it does not compare proximity modes or assess performance across fields.

With the ignored local API credential configured, run from the repository root:

```powershell
$env:PYTHONPATH = 'scripts'
python evals/screened-pilot/run.py runs/screened-pilot-repeat
```

Choose a new run directory. Each topic produces its own ID ledger and request
logs. [protocol.json](protocol.json) specifies the queries and source revision.
[results.json](results.json) preserves source checksums, source row IDs, DOI
resolution, canonical OQL, corpus membership and retrieved IDs for every run.

## Sources and attribution

The final-inclusion labels come from the original review teams via the
[pinned ASReview datasets](https://github.com/asreview/synergy-dataset/tree/38b35218e4d0f99621cec5a8a25a0147bb88c654).
The derived ledger retains identifiers and adds OpenAlex resolution and retrieval observations.

- Appenzeller-Herzog et al., Wilson disease therapies. Source labels under CC BY 4.0. [Review](https://doi.org/10.1111/liv.14179) · [Dataset](https://doi.org/10.5281/zenodo.3625931)
- Nagtegaal et al., nudging healthcare professionals. Source labels under CC0. [Review](https://doi.org/10.30636/jbpa.22.71) · [Dataset](https://doi.org/10.7910/DVN/WMGPGZ/HY6N2S)
- van Dis et al., long-term outcomes of cognitive behavioral therapy. Source labels under CC BY 4.0. [Review](https://doi.org/10.1001/jamapsychiatry.2019.3986) · [Dataset](https://osf.io/4d9tu/)
