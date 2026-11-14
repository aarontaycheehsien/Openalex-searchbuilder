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

## Compound proximity

On 2026-11-14 the title/abstract query `"climate change"~3 OR climatology`
across all corpora reproduced HTTP 500 at `POST /query` in a single OQO leaf.
Executing that leaf directly returned 1,329,906 works. Native OQL expressed the
window as `(climate and change within 3 words of each other)` and returned
1,348,698 works. Even placing a legacy phrase-slop operand in a separate
structured filter can yield canonical OQL that selects a different count when
replayed. A successful validation response alone does not establish equivalence.

The opt-in `oql` proximity mode compiles to the scoped filter structure observed
from OpenAlex. The live regression checks the compiler against independently
posted OQL, then executes both the validated OQO and the canonical OQL and
compares counts and the first three returned IDs. The follow-up suite passed
37 offline tests and three authenticated live tests. Counts above are observations
from the investigation and may change as OpenAlex updates.

OpenAlex documents translation at `POST /query` and execution at `POST /`.
See the [OQL API](https://help.openalex.org/api/oql/), the
[OQL proximity grammar](https://help.openalex.org/access/oql-spec/), and the
[phrase-slop search documentation](https://help.openalex.org/api/searching/).

These checks establish API behavior for the tested queries. Measuring recall or
comparing search effectiveness still requires independently screened multidisciplinary
benchmarks. See [evaluation fixtures](evals/README.md), [review findings](REVIEW.md)
and the [test commands](README.md#tests).
