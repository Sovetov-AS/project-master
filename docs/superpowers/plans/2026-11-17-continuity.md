# Continuous memory Implementation Plan

> For agentic workers: use superpowers:subagent-driven-development or superpowers:executing-plans task by task.

**Goal:** Resume long development accurately with bounded context and recoverable local search.
**Architecture:** Existing source stores remain authoritative. A versioned private sidecar maintains curated source metadata, explicit graph edges and experiment lifecycle; SQLite is derived. Recovery attaches a bounded freshness-aware context.
**Tech Stack:** Python standard library SQLite; optional FastEmbed local ONNX embeddings.
**Spec:** ../specs/2026-11-17-continuity.md

## Global Constraints

No automatic project migration, secret indexing, remote embedding calls, unrequested publication of owner memory, or deletion of archived artifacts. Preserve STATE/MISSION 3.0. Approximate token counts must be labelled. Explicit graph links only.

## Review Focus

Dirty files, changed branches, stale checks, corrupt index and overflow must remain visible. Symlink/path escapes are rejected. Archived active defects cannot become normal experiment records.

## Tasks

- [x] Add tests in tests/test_memory.py: freshness after source mutation; budget overflow keeps mandatory core; archive excludes body but retains lesson; graph source validation; corrupt index graceful fallback; vector identity and semantic retrieval.
- [x] Implement scripts/development_memory.py: enable(root, apply=False), register(root, id, path, kind, summary), checkpoint(root), context(root, core, budget=3000), archive(root, id, lesson), link(root, source, target, relation, evidence), index(root, semantic=False), search(root, query, limit=5, include_archive=False).
- [x] Add scripts/local_embeddings.py with explicit local FastEmbed model loading, model identity and strict finite vector validation. Install optional runtime only in isolated validation environment.
- [x] Extend recover.py using optional sidecar with bounded mandatory core, no compatibility break for existing callers.
- [x] Add operational reference and README commands; document explicit enable plan/apply and backup, experiment eligibility and periodic archiving checkpoints.
- [x] Run unittest suite, compileall, CLI smoke and real embedding benchmark; record exact evidence and remaining limits.
