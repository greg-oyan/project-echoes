# Methodology

## Milestone 0

Milestone 0 establishes reproducible infrastructure only. Configuration is strict and versioned, dependencies are locked, generated manifests record repository and environment state, and the quality gate runs formatting, linting, typing, and tests.

No corpus, detector, embedding model, alignment, or candidate-generation method is active. Configuration entries for later work are declarations of intent, not implemented research methods or evidence.

## Reproducibility assumptions

- Python is fixed to the 3.12 series through `.python-version` and `pyproject.toml`.
- Direct and transitive Python dependencies are fixed by exact requirements and `uv.lock`.
- Configuration parsing rejects undocumented fields.
- A run manifest records configuration and lockfile hashes, Git state, Python version, hardware summary, model declarations, warnings, and errors.
- Generated outputs are local and excluded from Git unless a later milestone explicitly approves a publishable derived artifact.

Detailed corpus and experimental methodology begins only after the research and governance gate in Milestone 1.

## Milestone 1

Milestone 1 fixes the research charter, corpus roles, evidentiary language, source lifecycle, and methodology change control before data selection can be influenced by attractive results. Source records are strict metadata documents: unresolved values are explicit `null` or enum states, unsafe lifecycle transitions fail, and no record is equivalent to activation.

The preliminary literature comparison uses primary papers and project repositories. It identifies known component methods and methodological traps; it supports only a provisional integration statement. The literature matrix will expand before candidate-level novelty review.

Experiment YAML now records research questions, inputs, methods, parameters, evaluation data, outputs, acceptance criteria, prohibited claims, seed, and lifecycle status. These are governance declarations only; no listed experiment is implemented in Milestone 1.
