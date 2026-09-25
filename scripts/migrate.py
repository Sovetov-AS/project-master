#!/usr/bin/env python3
"""Plan or explicitly apply the Project Master 2.0 to 2.1 state migration."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import state as pm_state


def load_legacy(root: Path) -> Dict[str, Any]:
    path = pm_state.state_path(root)
    if not path.is_file():
        raise pm_state.StateError(f"STATE not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise pm_state.StateError(f"2.1 migration supports JSON-compatible STATE only: {exc}") from exc
    if not isinstance(data, dict):
        raise pm_state.StateError("STATE root must be a mapping")
    if data.get("schema_version") != "2.0":
        raise pm_state.StateError(f"expected schema_version 2.0, got {data.get('schema_version')}")
    return data


def plan(root: Path) -> int:
    data = load_legacy(root)
    approved = [area for area in pm_state.APPROVALS if data.get("approvals", {}).get(area)]
    print("MIGRATION PLAN (read-only)")
    print("Source schema: 2.0")
    print("Target schema: 2.1")
    print(f"Approved areas to bind to current artifact hashes: {', '.join(approved) or 'none'}")
    print("1. Back up STATE.yaml and CURRENT_STATE.md under .project-master/migrations/.")
    print("2. Add lifecycle profile, capability routing, active change, and event-log fields.")
    print("3. Bind existing approvals to the current artifacts only with explicit acceptance.")
    print("4. Create ROUTING.md and the first hash-chained state event.")
    print("5. Run state.py validate and validate_project.py after migration.")
    return 0


def add_current_state_fields(path: Path, profile: str, routing: Dict[str, Any]) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if not re.search(r"(?m)^Profile:", text):
        text = re.sub(r"(?m)^(Status:.*)$", rf"\1\n\nProfile: {profile}", text, count=1)
    if not re.search(r"(?m)^Change:", text):
        text = re.sub(r"(?m)^(Component:.*)$", r"\1\n\nChange: —", text, count=1)
    if not re.search(r"(?m)^Routing:", text):
        route = f"{routing['required_capability']} / {routing['minimum_effort']}"
        text = re.sub(r"(?m)^(Change:.*)$", rf"\1\n\nRouting: {route}", text, count=1)
    pm_state.atomic_write(path, text)


def apply(root: Path, accept_current: bool) -> int:
    root = root.resolve()
    data = load_legacy(root)
    approved = [area for area in pm_state.APPROVALS if data.get("approvals", {}).get(area)]
    if approved and not accept_current:
        raise pm_state.StateError(
            "approved areas exist; rerun with --accept-current-approved-artifacts after reviewing the plan"
        )
    pm = pm_state.project_dir(root)
    if pm_state.event_log_path(root).exists():
        raise pm_state.StateError("state-events.jsonl already exists; refusing ambiguous migration")
    timestamp = pm_state.now()
    backup = pm / "migrations" / f"2.0-to-2.1-{timestamp.replace(':', '').replace('-', '')}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(pm / "STATE.yaml", backup / "STATE.yaml")
    current = pm / "CURRENT_STATE.md"
    if current.is_file():
        shutil.copy2(current, backup / "CURRENT_STATE.md")
    routing = {
        "mode": "advisory",
        "quality_profile": "balanced",
        "required_capability": "balanced_reasoning",
        "minimum_effort": "medium",
        "reason": "Migrated safe default; reassess per work package",
        "selected_at": timestamp,
    }
    data.update({
        "schema_version": pm_state.VERSION,
        "project_master_version": pm_state.VERSION,
        "lifecycle_profile": "FULL",
        "profile_record": {
            "profile": "FULL", "at": timestamp, "source": "2.0 migration",
            "reason": "Preserve full lifecycle until a new change is classified",
        },
        "active_change": None,
        "routing": routing,
        "event_log": ".project-master/state-events.jsonl",
        "updated_at": timestamp,
    })
    records = data.setdefault("approval_records", {})
    for area in approved:
        artifact_hash, artifacts = pm_state.approval_snapshot(root, area)
        previous = records.get(area) if isinstance(records.get(area), dict) else {}
        records[area] = {
            **previous,
            "approved": True,
            "artifact_hash": artifact_hash,
            "artifacts": artifacts,
            "migrated_at": timestamp,
            "migration_note": "Current artifacts explicitly accepted as the 2.0 approval baseline",
        }
    pm_state.atomic_write(pm / "STATE.yaml", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    routing_target = pm / "ROUTING.md"
    if not routing_target.exists():
        template = Path(__file__).resolve().parent.parent / "assets" / "templates" / "ROUTING.md"
        pm_state.atomic_write(routing_target, template.read_text(encoding="utf-8"))
    add_current_state_fields(current, "FULL", routing)
    pm_state.append_event(root, "project.initialized", data, {
        "migrated_from": "2.0", "backup": backup.relative_to(pm).as_posix(),
        "accepted_current_approved_artifacts": bool(approved),
    })
    errors = pm_state.validate_state(data)
    errors.extend(pm_state.approval_integrity_errors(root, data))
    errors.extend(pm_state.validate_event_log(root, data))
    if errors:
        raise pm_state.StateError("migration produced invalid state: " + "; ".join(errors))
    print(f"PASS: migrated Project Master state to 2.1; backup: {backup}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--accept-current-approved-artifacts", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "plan":
            return plan(args.root.resolve())
        return apply(args.root.resolve(), args.accept_current_approved_artifacts)
    except (OSError, pm_state.StateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
