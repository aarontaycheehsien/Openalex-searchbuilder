# Upstream attribution

Derived from https://github.com/aarontaycheehsien/pubmed-search-builder-next
at commit 704317b4fc954746d24950f80d4b7f7e90a3e74a (MIT; see LICENSE.upstream).

Retains its agent-operated concept-block workflow, protocol/strategy separation,
known-record roles, held-out protection, per-block diagnostics, critique packets,
fingerprinted validation and protected delivery design. Configuration parsing is
adapted directly from scripts/psb/config.py; the concept compiler, workspace,
evaluation and review machinery are rewritten for OpenAlex JSON and identifiers.

The PubMed backend, MeSH validation, historical-count assumptions and PubMed
performance results are not included. This adaptation has not inherited or
established the upstream empirical performance claims.
