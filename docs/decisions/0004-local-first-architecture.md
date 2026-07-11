# 0004 — Local-first architecture

- Status: Accepted
- Date: 2026-07-10

## Context

The biblical corpus is small enough for a research workstation, while some sources may be restricted from cloud storage or public redistribution. The project prioritizes reproducibility and scholarly inspection over service scale.

## Decision

Project Echoes uses a local-first Python 3.12 workflow with `uv`, Parquet, DuckDB, and Polars as later milestones require. Raw and restricted data remain in ignored local storage. No distributed system, cloud database, Kubernetes cluster, microservice architecture, authentication system, or SaaS layer is introduced for the core research pipeline.

## Rationale

Local execution reduces operational complexity, supports offline reprocessing, limits accidental redistribution, and makes experiments reproducible by another researcher without institutional infrastructure.

## Consequences

Acquisition instructions and checksums substitute for committed restricted data. Hardware and runtime are recorded. Later optimization must be evidence-driven; a public review interface is deferred until credible candidates exist.

## Alternatives considered

- Cloud-native data platform: rejected as unnecessary and potentially incompatible with source terms.
- Managed vector database: rejected before baselines demonstrate a need.
- Public application first: rejected because it would outpace evidence and review governance.
