---
name: openalex-search-builder
description: Build, review, or update an OpenAlex Boolean search for evidence synthesis across disciplines. Supports an explicitly requested offline untested draft, or the default empirical workflow with known-paper testing, critique, audit, and complete CSV/RIS export. Does not answer the review question.
---

# OpenAlex Search Builder

Use this skill through Codex or Claude Code. The agent develops vocabulary and
writes the protocol and strategy; the Python tool compiles, executes, measures,
and records evidence. It does not contain an LLM or generate synonyms itself.
Read `references/scope.md` and `references/anti-patterns.md` before development.

Run from the skill directory:

```bash
python scripts/osb.py --workspace <run-dir> <command>
```

All commands print JSON. Never invent counts, IDs, vocabulary verification or
recall. Report measurements only from successful commands in this workspace.
Relay returned progress text, and distinguish untested drafts from validated outputs.

## 1. Intake and scope

Ask for the review question, optional eligibility criteria and known relevant
records, required limits, and depth (quick/standard/thorough; default standard).
Default workflow is **validated**. Choose **draft** only when the user requests
untested/offline/Boolean-generation-only output. No API key is needed for draft.

Initialize with `init <run-dir> --question "..." [--mode draft] [--depth standard]`.
Write protocol.json: stable concept IDs, names, roles (`search`, `screen`,
`optional`) and rationales; eligibility include/exclude lists; assumptions in notes.
Question and eligibility define scope, never the seeds. Keep unnecessary outcomes,
comparators, settings and study designs for screening. Show the scope and ask the
user to keep or revise it unless they already authorized proceeding autonomously.
Run `scope --confirm` only when approval or that authorization exists.

Defaults are title + abstract + keywords and core + expansion (`corpus=all`).
Offer title + abstract only or full text + title + abstract + keywords when useful.
Use `configure --fields title_abstract|title_abstract_keywords|fulltext`,
`--corpus core|all|expansion`, and `--matching stemmed|exact` to change settings.
Every setting is part of the reproducible query. Never change it just to make a
warning disappear. No automatic date, language, article-type or open-access limits.

## 2. Offline draft branch

When mode is draft, **do not use any external source or network tool**, including
browser, shell HTTP, academic connectors or another API. The CLI blocks its own
network operations, but you must also honor this rule outside the CLI.

Develop synonyms from supplied material and general knowledge. Write concept
blocks into strategy.json (see examples). Use local `lint`, then `draft`.
Do not claim the proposed vocabulary exists in an OpenAlex authority.
Deliver draft-query.txt, draft-query.json and draft-notes.md, explicitly labeled
**Untested draft — not validated against OpenAlex.** Include assumptions and
selected fields/corpus. There are no live counts, recall claims or validation manifests.
Do not run critic, report, discovery, or export as substitutes for draft generation.

If the user later asks to test it, run `mode validated` in the same workspace and
continue below. Preserve the original draft files. All normal gates still apply.

## 3. Known records (validated mode)

Read references/known-records.md. Resolve IDs/DOIs/PMIDs/PMCIDs with `resolve`;
ambiguity and failures remain explicit. Add user-supplied seeds using
`set add seeds W... --role seed --source "user"`.

At standard/thorough depth, find additional candidates with precise pilot
strategies, `sample --purpose pilot|prior-reviews`, or `neighbors W... --kind
references|citing|related`. These commands use the current strategy; preserve
candidate and strategy history when moving from pilots to the final formulation.
Screen against eligibility using `screen W... --decision include|exclude|uncertain
--reason "..."`. Only included discoveries enter relevant/benchmark sets.

Prior-review reference lists are candidate pools, not automatically included
studies. Verify eligibility and review inclusion from available evidence; retain
uncertain records without treating them as relevant when evidence is insufficient.

With about ten development records, use `set split seeds --fraction 0.3` before
term mining. Validation/benchmark records must not be inspected for terminology.
If they influence revision, remove them from their old set and reclassify them
as relevant; screen include first. Independence cannot be restored by renaming.
Quick mode may skip discovery when no seeds are supplied. Every mode states
when relative recall cannot be measured.

## 4. Vocabulary and strategy

Read references/vocabulary.md and references/filters.md. Write one block per
searched concept, with matching IDs. Terms within a block are OR-ed; blocks are
AND-ed by default. A `combine` expression may reference block IDs with AND/OR/NOT.
Use `vocab keywords "..."` or `vocab topics "..."` for live suggestions, and
`terms rank` for development-record terms. Topics and keywords are not MeSH and
are not a compulsory controlled-vocabulary layer. Do not use deprecated concepts.

The global matching mode is stemmed by default. Wildcards require explicitly
selecting exact matching and reassessing all terms; the tool never silently
switches morphology. Use three leading characters before a wildcard. Phrase
proximity is `"climate change"~5`. Unsupported syntax fails rather than translating
PubMed tags or silently weakening the expression.

## 5. Evaluate and revise

Run `eval --note "change and reason"` after meaningful changes. Read every line
count, per-set relative recall and coverage, misses, failing blocks, limit losses,
block ablation, and known_lost. Inspect development misses with `terms miss`.
Ablation is only defined here for the default AND combination; custom combinations
are reported as not assessed. Test explicit variants when needed.

Never silently lose a previously retrieved record. Revert or record a substantive
reason. Fix misses or explain retained misses with evidence. Separate records
unavailable in OpenAlex or outside the selected corpus from query failures.
Use `sample --purpose noise-check` to inspect noise; this is a bounded relevance
sample, not an unbiased precision estimate. Recall takes priority over low counts.

## 6. Critique

Read references/critic.md. Generate `critic packet`, provide the packet to a fresh
review context if available, and save its response JSON. If no independent context
is available, review it yourself and set fresh_context=false. Never pretend a
fresh reviewer was used. Run `critic check --file <response.json>`.

The response must identify its reviewer, summarize the review, acknowledge every
warning, and explain every finding's disposition. Open findings block delivery.
Technical findings cannot be accepted as risks. After changes, evaluate and issue
a new packet. Preserve earlier objections. Quick/standard/thorough allow 1/2/3
revision packets, then a closing packet and one verification packet. Closing
rounds address previous findings; new technical blockers still block.

## 7. Validate, deliver and export

Read references/validation.md and references/reporting.md. Run `report`. It
revalidates live, checks current scope and critique, and writes final-query.txt
(canonical OQL), final-query.json, audit.md and validation-manifest.json only on
success. Changed interpretation or known-record evidence requires reevaluation
and review. `report --diagnostic` checks without producing final artifacts.

Deliver generated artifacts verbatim; never hand-author a validated manifest.
Then run `export` to traverse the complete result set and produce CSV, RIS and
JSONL. Export is automatically resumable. If it stops, give the partial status
and rerun after the cause is fixed. Never label partial files complete. Query
changes create a different export directory. Large retrievals consume API budget;
report the service's actual usage and exhaustion, not a guessed free allowance.

## Updates and existing strategies

For review, obtain the question, transcribe the existing OpenAlex strategy into
blocks, and assess it without changing scope. PubMed syntax is not automatically
translated. For updates, preserve the existing workspace and artifacts, make
explicit changes, and repeat evaluation/critique/report. Publication-date filters
are not historical database snapshots; current metadata and keyword assignments
can change old-query results.
