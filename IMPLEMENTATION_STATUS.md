# Implementation status

## Verification on 2026-11-14

Windows, Python 3.14.3, standard-library unittest. The offline run passed 36 tests
and skipped the two opt-in network tests. The authenticated live run passed both
tests in 46.7 seconds. Its request log counted 52 successful uncached requests,
each with rate-limit headers, and zero request errors. Earlier diagnostic probes
and reruns also consumed API budget. A total billed credit figure was not measured.

| Live check | Observed result |
| --- | --- |
| Scoped Boolean search | Direct OQO validation and execution accepted the explicit operator `has`. All three field modes returned results. |
| Known-work intersections | The service translated the OpenAlex work-ID filter to `ids.openalex`. Each mode retrieved a returned ID through the intersection. |
| Corpus and request size | Expansion search returned an `is_xpac` work. A serialized OQO over 8,190 bytes validated and executed via POST. |
| Matching | Exact title/abstract search for `climat*` and stemmed title/abstract proximity search for `"climate change"~3` both validated and returned records. |
| Report and export | Evaluation, critique, fresh validation and export completed for a one-work query. A separate two-ID query used one record per page. After an intentional interruption, export reused the saved cursor and returned both expected IDs. |

## Remaining limits

Direct validation of `"climate change"~3 OR climatology` in a single scoped
text-search leaf returned HTTP 500. The service's URL translator split the
expression into separate leaves. The compiler preserves the requested single
search scope and requires successful validation for delivery. Standalone proximity
phrases are emitted without redundant wrappers, which also triggered HTTP 500.

These checks establish API behavior for the tested queries. Measuring recall or
comparing search effectiveness still requires independently screened multidisciplinary
benchmarks. See [evaluation fixtures](evals/README.md), [review findings](REVIEW.md)
and the [test commands](README.md#tests).
