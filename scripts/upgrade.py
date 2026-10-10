#!/usr/bin/env python3
"""Explicit, backed-up 2.1 -> 3.0 migration. Owner content and history are retained."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import uuid
from pathlib import Path
import state
import mission
import init_project


def preflight(root: Path):
    data = state.load_state(root)
    if data.get("schema_version") != "2.1":
        raise state.StateError("upgrade expects 2.1; use migrate.py for 2.0 first; 3.0 is already upgraded")
    errors = state.validate_state(data) + state.validate_event_log(root, data) + state.approval_integrity_errors(root, data)
    if errors:
        raise state.StateError("repair pre-existing drift before migration: " + "; ".join(errors))
    pm = state.project_dir(root)
    if pm.is_symlink() or any(path.is_symlink() for path in pm.rglob("*")):
        raise state.StateError("memory symlinks need explicit review before backup/migration")
    if (pm / "private" / "MISSION.json").exists():
        raise state.StateError("pre-existing mission needs explicit reconciliation; never overwrite personal learning")
    agents = root / "AGENTS.md"
    content = agents.read_text(encoding="utf-8") if agents.exists() else ""
    for marker in (init_project.MANAGED_START, init_project.MANAGED_END):
        if content.count(marker) != 1:
            raise state.StateError("expected one existing managed AGENTS section; review missing/duplicate markers")
    private_ignore = pm / "private" / ".gitignore"
    if private_ignore.exists() and private_ignore.read_text(encoding="utf-8") != "*\n!.gitignore\n":
        raise state.StateError("review existing private ignore policy before migration")
    return data, content


@state.serialized
def apply(root: Path, definition, source: str, profile=None):
    root = root.resolve()
    if not source.strip():
        raise state.StateError("record the actual current owner instruction source")
    mission.validate_definition(definition)
    data, agents = preflight(root)
    pm = state.project_dir(root)
    private = pm / "private"
    private.mkdir(exist_ok=True, mode=0o700)
    ignore = private / ".gitignore"
    if not ignore.exists():
        state.atomic_write(ignore, "*\n!.gitignore\n")
    backup = private / "migrations" / ("2.1-to-3.0-" + state.now().replace(":", "") + "-" + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, mode=0o700)
    def ignored(directory, names):
        if Path(directory) == private:
            return ["migrations"] if "migrations" in names else []
        return [name for name in names if name in {"STATE.lock", "MISSION.lock"}]
    shutil.copytree(pm, backup / "memory", ignore=ignored)
    state.atomic_write(backup / "AGENTS.md", agents)
    old_hash = state.state_digest(data)
    state.atomic_write(backup / "receipt.json", json.dumps({"from": "2.1", "to": "3.0", "source": source,
        "state_sha256": old_hash, "scope": "all project memory except prior private migration backups and locks",
        "restore": "stop writers; restore memory/ and AGENTS.md together; do not reset event history piecemeal"}, ensure_ascii=False, indent=2) + "\n")
    mission.initialize(root, definition, source)
    # Rebind only already-valid approvals to the 3.0 normalization, never bless stale ones.
    for area in state.APPROVALS:
        if data["approvals"].get(area):
            record = data["approval_records"][area]
            digest, artifacts = state.approval_snapshot(root, area, "3.0")
            record["migration_baseline"] = {"artifact_hash": record["artifact_hash"], "snapshot_version": record.get("snapshot_version", "2.1")}
            record.update(artifact_hash=digest, artifacts=artifacts, snapshot_version="3.0", migrated_at=state.now())
    (pm / "workflows").mkdir(exist_ok=True)
    updated_agents = re.sub(re.escape(init_project.MANAGED_START) + r".*?" + re.escape(init_project.MANAGED_END),
                            lambda match: init_project.MANAGED_SECTION, agents, flags=re.S)
    state.atomic_write(root / "AGENTS.md", updated_agents)
    data["schema_version"] = "3.0"
    data["project_master_version"] = "3.0"
    if profile:
        data["lifecycle_profile"] = profile
        data["profile_record"] = {"profile": profile, "source": source, "at": state.now(), "reason": "Explicit 3.0 migration profile"}
    data["migration"] = {"from": "2.1", "at": state.now(), "source": source, "backup": str(backup.relative_to(root))}
    state.save_state(root, data, "project.migrated", data["migration"])
    state.ensure_event_log_current(root)
    print(f"PASS: Project Master 3.0; full memory backup: {backup}")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    change = sub.add_parser("apply")
    change.add_argument("--mission", type=Path, required=True, help="Private, reviewed goal definition; never a public skill asset with owner data")
    change.add_argument("--source", required=True)
    change.add_argument("--profile", choices=state.LIFECYCLE_PROFILES)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            data, _ = preflight(args.root.resolve())
            print(json.dumps({"from": "2.1", "to": "3.0", "stage": data["stage"], "active_component": data.get("active_component"),
                "profile": data["lifecycle_profile"], "preserve": "all project content, unknown state fields, approval provenance and event history",
                "change": "private goal memory, compact checkpoint, managed AGENTS block, progress-aware hashes",
                "requires": "owner migration instruction and reviewed private mission definition",
                "not_authorized": "live operations, paid calls, personal-data publication or installation of project products"}, ensure_ascii=False, indent=2))
        else:
            apply(args.root.resolve(), mission.read_json(args.mission), args.source, args.profile)
        return 0
    except (state.StateError, mission.MissionError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
