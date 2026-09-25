# CAPABILITY ROUTING

Status: `ACTIVE`

Project Master records the capability needed for a work package, not a permanent model name. Runtime availability and current model documentation determine the concrete executor.

## Current policy

- Mode: `advisory`
- Quality profile: `balanced`
- Required capability: `balanced_reasoning`
- Minimum effort: `medium`

## Escalation triggers

- conflicting requirements or sources of truth;
- repeated verification failure;
- security, permissions, irreversible migration, or production risk;
- architecture or cross-component changes;
- need for independent review.

## Decision log

Routing decisions are stored in `STATE.yaml` and `state-events.jsonl`.
