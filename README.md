# OpenAlex Search Builder

An agent skill for **Codex and Claude Code** that develops Boolean searches for
systematic, scoping and other evidence reviews across disciplines. Adapted from
[PubMed Search Builder](https://github.com/aarontaycheehsien/pubmed-search-builder-next)
under MIT; see [UPSTREAM.md](UPSTREAM.md).

Two workflows:

- **Validated (default):** scope → known papers → vocabulary → execution and miss
  diagnosis → revision → internal critique → live validation → audit → full export.
- **Draft-only:** generate an untested Boolean strategy offline, without an API
  key or external calls. Local syntax checks are not OpenAlex validation.

Default fields are **title + abstract + keywords**, searching **core + expansion**.
Title + abstract and title + abstract + keywords + full text are selectable.

## Use as a skill

Ask your coding agent:

> Read SKILL.md and build an OpenAlex strategy for a review of urban tree cover
> and heat mitigation. Use draft-only mode.

Or:

> Read SKILL.md and develop and test an OpenAlex search for my review. Use
> standard depth, these eligibility criteria, and these seed DOIs: [...].

The agent writes the question-specific vocabulary and scope; the Python CLI is
the execution and audit tool, not a standalone language model. Read
[SKILL.md](SKILL.md) for the complete workflow.

## Setup

Python 3.10+; no runtime packages required.

```bash
cp .env.example .env
# Add OPENALEX_API_KEY when ready for authenticated requests and cursor paging.
python scripts/osb.py doctor
```

Never commit the key. Network execution uses bearer authorization, bounded retries,
credential-redacted logs and per-workspace cache. `OSB_CACHE=0` disables cache reads.
Authenticated live checks on 2026-11-14 verified the three search field modes,
work-ID intersections and validated export. Compound proximity expressions can
still fail OpenAlex validation. See [verification results](IMPLEMENTATION_STATUS.md).

## Try the offline example

```bash
python scripts/osb.py init runs/urban-trees --question "Urban trees and heat mitigation" --mode draft
cp examples/urban-trees.strategy.json runs/urban-trees/strategy.json
cp examples/urban-trees.protocol.json runs/urban-trees/protocol.json
python scripts/osb.py -w runs/urban-trees lint
python scripts/osb.py -w runs/urban-trees draft
```

This produces draft-query.txt, draft-query.json and draft-notes.md. The supplied
example is untested and has no claimed recall or OpenAlex count.

## Move into tested development

```bash
python scripts/osb.py -w runs/urban-trees mode validated
# Confirm only after the user has approved scope or authorized autonomous scope decisions:
python scripts/osb.py -w runs/urban-trees scope --confirm
python scripts/osb.py -w runs/urban-trees resolve https://doi.org/10.1234/example
# Use actual resolved W IDs, then screen discoveries and populate sets.
python scripts/osb.py -w runs/urban-trees eval --note "Initial candidate"
python scripts/osb.py -w runs/urban-trees critic packet
# Have the agent/reviewer write a response to that packet:
python scripts/osb.py -w runs/urban-trees critic check --file review.json
python scripts/osb.py -w runs/urban-trees report
python scripts/osb.py -w runs/urban-trees export
```

The DOI above is a placeholder, not a known relevant paper. Commands require
current workspace state; critique and delivery intentionally fail when missing.

| Commands | Purpose |
| --- | --- |
| init, mode, configure, scope, status | Manage scope and explicit search settings |
| draft, lint | Offline query generation and local checks |
| count, sample, fetch, resolve | Execute queries and inspect development records |
| neighbors, vocab | Candidate discovery and keyword/topic lookup |
| screen, set | Screening, role separation, deterministic validation split |
| eval, terms rank/miss | Measurement, diagnosis and development vocabulary |
| critic packet/check, report | Evidence-bound internal review and live delivery gate |
| export | Complete, resumable CSV/RIS/JSONL export |
| progress, log, cache, doctor | Progress, provenance, cache and configuration |

Run `python scripts/osb.py <command> --help` for arguments. Global `-w` comes
before the command. Every command prints JSON; errors exit nonzero.

## Strategy format

See [examples/urban-trees.strategy.json](examples/urban-trees.strategy.json).
Terms are strings; compound alternatives may contain parentheses and uppercase
AND/OR/NOT. `combine` defaults to AND of blocks, or references block IDs explicitly.
Limits are OQO leaf filters with a mandatory rationale. Field tags such as `[tiab]`
are rejected. Wildcards require explicit `matching: "exact"`; this affects the
entire strategy, so inspect and retest morphology when changing it.

The compiler targets the documented OQO query API, validates via POST `/query`,
and executes via POST `/`. Server canonicalization is retained as OQL. If the
service contract changes, the tool fails rather than silently using a different
search. The selected corpus is explicit in every query and diagnostic.

## Output and reproducibility

Validated report: final-query.txt, final-query.json, audit.md, validation-manifest.json.
Export: exports/<query-hash>/<validation-hash>/results.csv, results.ris, results.jsonl, checkpoint.sqlite3,
and export-manifest.json. Partial files contain `.partial` in their names.

Exports checkpoint each page atomically and deduplicate OpenAlex IDs. Each newly validated report starts a new export, even when its query is unchanged.
Repeated export commands for the same report resume that retrieval. CSV escapes formula-like text; JSONL preserves the original
values. Available metadata may be incomplete, and abstracts/full text are not
available for every record. No PDFs are downloaded. Paging completion does not
make the changing OpenAlex index a historical snapshot; count discrepancies are
reported. Existing partial files remain historical partial artifacts after resume;
use the files listed in the latest export manifest.

Draft artifacts never imply validation. Test-corpus recall is not complete
sensitivity; development recall is not independent validation. OpenAlex topics
are not MeSH. Internal critique is not formal PRESS peer review.

## Tests

All offline tests use Python's standard-library unittest runner:

```bash
PYTHONPATH=scripts python -m unittest discover -s tests -v
```

Opt-in live tests require the API key and make real requests (consuming its budget):

```bash
OSB_LIVE_TESTS=1 PYTHONPATH=scripts python -m unittest discover -s tests -p test_live.py -v
```

See [evals/README.md](evals/README.md) for multidisciplinary development and held-out
fixtures. Synthetic tests do not establish real search effectiveness. No upstream
PubMed performance claims are carried over.

## Recheck fixes

See [REVIEW.md](REVIEW.md) for the second-pass findings and regression coverage.
