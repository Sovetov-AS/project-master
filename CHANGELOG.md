# Changelog

All notable changes to Project Master are documented here.

## 2.1 — 2026-09-25

- Added adaptive `QUICK`, `STANDARD`, `FULL`, and `CRITICAL` lifecycle profiles.
- Added capability-based model routing without hard-coded model assignments.
- Bound approvals to SHA-256 snapshots of the approved artifacts.
- Added append-only `state-events.jsonl` with state integrity validation.
- Added structured change packages with proposal, delta, impact, plan, and verification files.
- Added an explicit, backed-up 2.0 to 2.1 migration with approval-baseline confirmation.
- Expanded behavioral tests for approval drift, event integrity, routing, profiles, and change packages.
- Added the MIT License with copyright attribution to Andrey Sovetov.

## 2.0 — 2026-09-24

- Initial public release with repository memory, human gates, BPMN, roadmap, recovery, verification, and change control.
