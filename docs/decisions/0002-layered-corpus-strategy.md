# 0002 — Layered corpus strategy

- Status: Accepted
- Date: 2026-07-10

## Context

Project Echoes needs primary texts, translations, annotations, cross-references, textual witnesses, and reception sources. Treating them as one merged corpus would erase edition, evidentiary, and licensing distinctions.

## Decision

Every source receives one governed role: primary discovery, bridge, supplementary annotation, textual validation, reception history, benchmark, or reference. Added datasets remain parallel layers and never become primary targets or overwrite annotations without an explicit later decision.

## Rationale

Layering preserves provenance and makes claims match evidence. It keeps a Septuagint bridge distinct from Hebrew primary text, a cross-reference benchmark distinct from textual evidence, and later reception distinct from authorial-dependence claims.

## Consequences

Schemas and tables must retain source IDs, versions, conflicts, and alignment confidence. Experiments must declare exact layers. Integration costs more storage and alignment work, but avoids an opaque composite corpus.

## Alternatives considered

- One reconciled canonical database: rejected because reconciliation would hide disagreements.
- Activate any permissive dataset immediately: rejected because availability does not demonstrate research value or quality.
- Treat all ancient witnesses as equal discovery corpora: rejected because they answer different research questions.
