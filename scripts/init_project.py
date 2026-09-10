#!/usr/bin/env python3
"""Initialize repository-local Project Master memory without touching production code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

VERSION = "2.0"
MANAGED_START = "<!-- project-master:start -->"
MANAGED_END = "<!-- project-master:end -->"
MANAGED_SECTION = """<!-- project-master:start -->
## Project Master managed rules

- Project memory is stored in `.project-master/`; conversation history is not a source of truth.
- Run recovery before substantial work and follow approved requirements, BPMN processes, architecture, and roadmap.
- Route scope changes through Change Control.
- Mark work COMPLETE only with saved verification evidence.
<!-- project-master:end -->"""

ROOT_TEMPLATES = (
    "STATE.yaml", "CURRENT_STATE.md", "VISION.md", "CONSTITUTION.md",
    "REQUIREMENTS.md", "ARCHITECTURE.md", "ROADMAP.md", "TRACEABILITY.md",
    "RISKS.md", "OPEN_QUESTIONS.md", "BUILD_LOG.md",
)


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def skill_root() -> Path:
    return Path(__file__).resolve().parent.parent


def render(text: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def safe_name(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-.")
    return value or "project"


def planned_paths(root: Path) -> List[Path]:
    pm = root / ".project-master"
    paths = [pm / name for name in ROOT_TEMPLATES]
    paths += [
        pm / "processes" / "INDEX.md",
        pm / "processes" / "BPMN_GUIDE.md",
        pm / "processes" / "system" / "PM-001-project-master-lifecycle.bpmn",
        pm / "processes" / "system" / "PM-001-project-master-lifecycle.md",
        root / "AGENTS.md",
    ]
    return paths


def write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(str(path), flags, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)


def update_agents(root: Path, dry_run: bool) -> str:
    path = root / "AGENTS.md"
    if path.exists():
        original = path.read_text(encoding="utf-8")
        has_start, has_end = MANAGED_START in original, MANAGED_END in original
        if has_start != has_end:
            raise RuntimeError("AGENTS.md contains an incomplete Project Master managed section")
        if has_start:
            return "preserved existing managed section"
        updated = original.rstrip() + "\n\n" + MANAGED_SECTION + "\n"
        if not dry_run:
            path.write_text(updated, encoding="utf-8")
        return "appended managed section"
    if not dry_run:
        write_new(path, MANAGED_SECTION + "\n")
    return "created AGENTS.md"


def upgrade_plan(root: Path) -> int:
    state = root / ".project-master" / "STATE.yaml"
    if not state.is_file():
        print("No existing Project Master state; use init instead.")
        return 1
    raw = state.read_text(encoding="utf-8")
    current = "unknown/non-JSON YAML"
    try:
        current = str(json.loads(raw).get("project_master_version", "unknown"))
    except (json.JSONDecodeError, AttributeError):
        pass
    print("MIGRATION PLAN (read-only)")
    print(f"Current version: {current}")
    print(f"Target version: {VERSION}")
    print("1. Back up .project-master/ and record a Git baseline when available.")
    print("2. Validate and map old STATE fields; do not discard unknown fields.")
    print("3. Diff templates and merge project-owned content instead of replacing it.")
    print("4. Validate BPMN pairs, traceability, approvals, and active component.")
    print("5. Request explicit approval before applying the migration.")
    return 0


def initialize(root: Path, name: str, idea: str, dry_run: bool) -> int:
    root = root.resolve()
    if not root.is_dir():
        raise RuntimeError(f"project root does not exist: {root}")
    pm = root / ".project-master"
    if pm.exists():
        raise RuntimeError(f"refusing to overwrite existing project memory: {pm}")
    templates = skill_root() / "assets" / "templates"
    missing = [name for name in ROOT_TEMPLATES if not (templates / name).is_file()]
    if missing:
        raise RuntimeError(f"skill templates missing: {', '.join(missing)}")
    timestamp = now()
    identifier = f"{safe_name(name).lower()}-{uuid.uuid4().hex[:8]}"
    values = {
        "PROJECT_ID": identifier,
        "PROJECT_NAME": name,
        "CREATED_AT": timestamp,
        "IDEA": idea.strip() or "`TBD — получить исходную идею в Discovery.`",
    }
    if dry_run:
        print("DRY RUN: would create")
        for path in planned_paths(root):
            print(path)
        return 0
    directories = (
        pm / "processes" / "as-is", pm / "processes" / "to-be",
        pm / "processes" / "system", pm / "decisions", pm / "phases",
        pm / "changes", pm / "spikes", pm / "reviews",
    )
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=False)
    for filename in ROOT_TEMPLATES:
        source = templates / filename
        write_new(pm / filename, render(source.read_text(encoding="utf-8"), values))
    shutil.copyfile(templates / "BPMN_GUIDE.md", pm / "processes" / "BPMN_GUIDE.md")
    lifecycle_target = pm / "processes" / "system" / "PM-001-project-master-lifecycle.bpmn"
    shutil.copyfile(templates / "PM-001-project-master-lifecycle.bpmn", lifecycle_target)
    lifecycle_hash = hashlib.sha256(lifecycle_target.read_bytes()).hexdigest()
    sidecar = f"""# PM-001: Жизненный цикл Project Master

Process ID: PM-001

Name: Жизненный цикл Project Master 2.0

Status: APPROVED

## Purpose

Показать обязательные gates, execution loop, verification и completion review Project Master.

## Trigger

Пользователь приносит идею или возобновляет проект.

## Actors

- Product owner
- Codex / Project Master

## Inputs

- Идея, repository и сохранённая project memory.

## Outputs and end states

- Проверенный проект либо контролируемый blocker/change review.

## Linked requirements and components

- Internal Project Master lifecycle; project requirements/components не применимы.

## Diagram path

`processes/system/PM-001-project-master-lifecycle.bpmn`

## Sync metadata

- SHA-256: `{lifecycle_hash}`
- Initialized: `{timestamp}`
"""
    write_new(pm / "processes" / "system" / "PM-001-project-master-lifecycle.md", sidecar)
    index = """# PROCESS INDEX

| ID | Name | Category | Status | BPMN | Sidecar |
|---|---|---|---|---|---|
| PM-001 | Жизненный цикл Project Master 2.0 | system | APPROVED | [diagram](system/PM-001-project-master-lifecycle.bpmn) | [details](system/PM-001-project-master-lifecycle.md) |
"""
    write_new(pm / "processes" / "INDEX.md", index)
    agents_result = update_agents(root, dry_run=False)
    print(f"PASS: initialized {pm}")
    print(f"PASS: {agents_result}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--name")
    parser.add_argument("--idea", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--upgrade-plan", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.upgrade_plan:
            return upgrade_plan(args.root.resolve())
        return initialize(args.root, args.name or args.root.resolve().name, args.idea, args.dry_run)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
