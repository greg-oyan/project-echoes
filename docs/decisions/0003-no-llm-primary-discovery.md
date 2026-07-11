# 0003 — No LLM primary discovery

- Status: Accepted
- Date: 2026-07-10

## Context

Large language models can explain supplied text and generate useful research prompts, but their training exposure, nondeterminism, opaque retrieval, translation behavior, and tendency to produce unsupported claims conflict with the project's discovery and novelty standards.

## Decision

LLMs may not generate the primary candidate set, decide novelty, silently translate source text, assign final significance, or override deterministic evidence. After computational retrieval, an LLM may analyze a bounded evidence package for explanation, counterargument, search queries, or dossier drafting. Inputs, outputs, model/version, prompt, date, and limitations must be recorded.

## Rationale

Deterministic, inspectable discovery protects reproducibility and prevents model memory from masquerading as textual or scholarly evidence. Bounded later use retains the model's practical strengths without making it the evidentiary foundation.

## Consequences

The core pipeline remains runnable without a paid API. LLM observations must cite supplied evidence and remain advisory. Model ignorance can never justify a novelty claim.

## Alternatives considered

- Prompt an LLM for hidden biblical parallels: rejected as non-reproducible and exposure-prone.
- Use an LLM as final reviewer: rejected because final judgment requires traceable linguistic and scholarly review.
- Prohibit all LLM use: rejected because bounded critique and drafting can be useful when fully recorded.
