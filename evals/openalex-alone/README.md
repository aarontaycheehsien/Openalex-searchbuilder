# Can You Use OpenAlex Alone benchmark comparison

On 2026-11-14 we compared one Searchbuilder strategy per topic with selected published OQL arms. Each cell gives recovered benchmark works and the unrestricted OpenAlex result count. The latter estimates screening volume. Precision was not measured.

| Topic | Searchbuilder | Published OQL replay |
| --- | --- | --- |
| Diabetic eye screening, 130 indexed studies | 125/130 in 77,004 | Exploratory unscreen variant 130/130 in 3,816 |
| Digital CBT for insomnia, 29 included articles | 28/29 in 1,340 | Fuller 27/29 in 714, compact 27/29 in 1,544, fuller without trial filter 27/29 in 1,584 |
| Prospective depression biomarkers, 75 included articles | 48/75 in 16,746 | Fuller 66/75 in 353,164, compact 63/75 in 172,794 |
| Exercise for depression, 141 DOI-matched citations | 128/141 in 31,729 | Fuller 135/141 in 76,053, compact 131/141 in 40,333 |

The first three comparisons use the repository's verified work IDs, including the corrected Stansfield list. The live eye-screening run verified that W3159281016 redirects to W3217155492. Scoring maps the returned ID back to the original benchmark entry. The eye-screening comparator was developed on that benchmark. All original outcome counts published for the reference arms of the first three topics were reproduced, although unrestricted result counts have changed.

For exercise, the pinned source repository contains queries and a protocol. We downloaded its linked 218-row citation file and checked its SHA-256. Of 142 nonempty DOI fields, 141 uniquely matched a returned canonical DOI after normalizing DOI URLs. All 141 mapped to distinct works. Another 76 rows lacked a DOI and one supplied DOI did not match uniquely. The Searchbuilder strategy therefore recovered **at least 128/218 (58.7%)** overall. This partial check does not settle the upstream target of 208/218. An initial run undercounted matches because of dx.doi.org prefixes; the displayed results use corrected DOI normalization and identical queries. PMID and title/author/year adjudication remain open.

## Interpretation and reproduction

This is a retrospective, single-session known-work comparison. Published results and some published query text were visible before drafting. The Searchbuilder arms were frozen in commits c1d2fab and 63dac51 before their respective executions. They use the core corpus, title/abstract/keyword search, stemmed matching and upstream publication windows. They are illustrative strategies without a full iterative review. Membership was tested by adding ID restrictions to the validated query. No full result sets were downloaded. Counts and membership can change over time.

The [frozen protocol](protocol.json) contains the complete Searchbuilder strategies. The [result ledger](results.json) contains benchmark IDs, per-arm hits and misses, counts and exercise citation mappings. The runner fetches queries and benchmark inputs from the [pinned source repository](https://github.com/aarontaycheehsien/canyouuseopenalexalone/tree/455786472c1d1c2ff3a2e121e49d19eb91d02425). With the local OpenAlex key configured, run from the repository root using a new output directory:

```powershell
$env:PYTHONPATH = 'scripts'
python evals/openalex-alone/run.py runs/openalex-alone-repeat
```
