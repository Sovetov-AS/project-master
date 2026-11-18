#!/usr/bin/env python3
"""Read-only, goal-first recovery without reading the entire project archive."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import state
import mission
import plan_context


def recover(root: Path, budget: int = 3000, compact: bool = False):
    data = state.load_state(root)
    errors = state.validate_state(data) + state.validate_event_log(root, data)
    if (state.project_dir(root) / "pending-state.json").exists():
        errors.append("pending transaction: inspect then state.py repair")
    errors += state.approval_integrity_errors(root, data)
    snapshot = None
    if data.get("schema_version") == "3.0":
        snapshot = mission.snapshot(root)
    refs = [".project-master/REQUIREMENTS.md", ".project-master/ROADMAP.md"]
    if data.get("active_component"):
        path = state.find_component(root, data["active_phase"], data["active_component"])
        refs += [str(path.relative_to(root.resolve())), str(path.parent.parent.relative_to(root.resolve()) / "PLAN.md"),
                 str(path.parent.parent.relative_to(root.resolve()) / "CONTEXT.md")]
    result = {"engine": state.VERSION, "schema": data["schema_version"], "mission": snapshot,
            "stage": data["stage"], "profile": data["lifecycle_profile"],
            "active_component": data.get("active_component"), "active_change": data.get("active_change"),
            "next_action": data.get("next_action"), "last_verification": data.get("last_verification"),
            "blockers": data.get("blockers", []), "read_next": refs,
            "relevant_requirements": data.get("relevant_requirements", []),
            "relevant_processes": data.get("relevant_processes", []),
            "relevant_decisions": data.get("relevant_decisions", []), "errors": errors,
            "authority": "Historical approval is context, not new external-write authority",
            "limit": "Integrity/read-only recovery, not semantic review or runtime acceptance"}

    try:
        working_plan = plan_context.load(root)
        if working_plan is not None:
            result["working_plan"] = working_plan
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result["working_plan_warning"] = f"Working plan unavailable: {exc}"

    import development_memory
    if compact and development_memory.directory(root).exists():
        try:
            result = development_memory.context(root, result, budget)
            result['errors'] = result['core']['errors']
            result['estimated_tokens'] = development_memory.tokens(result)
            result['budget_exceeded'] = result['estimated_tokens'] > budget
        except (ValueError, OSError, KeyError) as exc:
            result['memory_warning'] = f'Development memory unavailable: {exc}'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--budget", type=int, default=3000)
    parser.add_argument("--compact", action="store_true", help="opt-in bounded development context")
    args = parser.parse_args()
    try:
        result = recover(args.root.resolve(), args.budget, args.compact)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result["errors"] else 0
    except (state.StateError, mission.MissionError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
