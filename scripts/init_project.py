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

import state as pm_state
import mission

VERSION = "3.0"
MANAGED_START = "<!-- project-master:start -->"
MANAGED_END = "<!-- project-master:end -->"
MANAGED_SECTION = """<!-- project-master:start -->
## Project Master managed rules

- Project memory is stored in `.project-master/`; conversation history is not a source of truth.
- Read the installed project-master SKILL.md, then run its scripts/recover.py --root <PROJECT_ROOT> after handoff or compaction.
- Restore private/MISSION.json: goal, current increment, strategy, outcomes and personal lessons. Do not export personal learning to the shared skill.
- Build the smallest useful increment, test a real scenario, preserve an extension seam, then extend. Product capabilities are distinct from live-operation permissions.
- Use editable product interaction maps when they clarify handoffs and scoped stops; BPMN is optional, never a mandatory lifecycle picture.
- Follow the current work contract. A clear user request can authorize its scope; do not demand repeated approval phrases. External, paid, destructive or production actions need the applicable current authority.
- Keep one memory writer and one ACTIVE component. Ordinary corrections need a brief log and tests, not a six-file change package.
- Mark work COMPLETE only with saved verification evidence.
<!-- project-master:end -->"""

ROOT_TEMPLATES = (
    "STATE.yaml", "CURRENT_STATE.md", "VISION.md", "CONSTITUTION.md",
    "REQUIREMENTS.md", "ARCHITECTURE.md", "ROADMAP.md", "TRACEABILITY.md",
    "RISKS.md", "OPEN_QUESTIONS.md", "BUILD_LOG.md", "ROUTING.md",
)
LEAN_TEMPLATES = ("STATE.yaml", "CURRENT_STATE.md", "VISION.md", "CONSTITUTION.md",
                  "REQUIREMENTS.md", "ROADMAP.md", "TRACEABILITY.md", "BUILD_LOG.md")


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


def planned_paths(root: Path, schema: str = VERSION) -> List[Path]:
    pm = root / ".project-master"
    if schema == VERSION:
        return [pm / name for name in LEAN_TEMPLATES] + [pm / "state-events.jsonl", pm / "private/MISSION.json",
            pm / "private/.gitignore", root / "AGENTS.md"]
    paths = [pm / name for name in ROOT_TEMPLATES]
    paths += [
        pm / "state-events.jsonl",
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
    if current == "2.0":
        print("Apply with: python3 scripts/migrate.py --root <PROJECT_ROOT> apply")
        print("If approvals exist, add --accept-current-approved-artifacts after reviewing current files.")
    return 0


def initialize(root: Path, name: str, idea: str, profile: str, dry_run: bool, schema: str = VERSION) -> int:
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
        "LIFECYCLE_PROFILE": profile,
    }
    if dry_run:
        print("DRY RUN: would create")
        for path in planned_paths(root, schema):
            print(path)
        return 0
    # Preflight existing owner rules before creating any project memory.
    update_agents(root, dry_run=True)
    directories = (
        pm / "processes" / "as-is", pm / "processes" / "to-be",
        pm / "processes" / "system", pm / "decisions", pm / "phases",
        pm / "changes", pm / "spikes", pm / "reviews",
    )
    if schema == VERSION:
        directories = tuple(pm / name for name in ("decisions", "phases", "changes", "reviews"))
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=False)
    for filename in (LEAN_TEMPLATES if schema == VERSION else ROOT_TEMPLATES):
        source = templates / filename
        text = render(source.read_text(encoding="utf-8"), values)
        if filename == "STATE.yaml":
            data = json.loads(text)
            data["schema_version"] = schema
            data["project_master_version"] = schema
            text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        write_new(pm / filename, text)
    if schema == VERSION:
        (pm / "workflows").mkdir()
        mission.initialize(root, initial_mission(identifier, idea), "bootstrap: initial idea; clarify acceptance with owner")
        pm_state.initialize_event_log(root, pm_state.load_state(root))
        pm_state.update_current_state(root, pm_state.load_state(root))
        update_agents(root, dry_run=False)
        print(f"PASS: initialized Project Master 3.0 {pm}; goal needs Discovery review")
        return 0
    shutil.copyfile(templates / "BPMN_GUIDE.md", pm / "processes" / "BPMN_GUIDE.md")
    lifecycle_target = pm / "processes" / "system" / "PM-001-project-master-lifecycle.bpmn"
    shutil.copyfile(templates / "PM-001-project-master-lifecycle.bpmn", lifecycle_target)
    lifecycle_hash = hashlib.sha256(lifecycle_target.read_bytes()).hexdigest()
    sidecar = f"""# PM-001: Жизненный цикл Project Master

Process ID: PM-001

Name: Жизненный цикл Project Master 2.1

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
| PM-001 | Жизненный цикл Project Master 2.1 | system | APPROVED | [diagram](system/PM-001-project-master-lifecycle.bpmn) | [details](system/PM-001-project-master-lifecycle.md) |
"""
    write_new(pm / "processes" / "INDEX.md", index)
    pm_state.initialize_event_log(root, pm_state.load_state(root))
    agents_result = update_agents(root, dry_run=False)
    print(f"PASS: initialized {pm}")
    print(f"PASS: {agents_result}")
    return 0


def initial_mission(identifier: str, idea: str) -> Dict:
    return {
        "goal_id": identifier,
        "goal": idea.strip() or "NEEDS_REVIEW: получить цель пользователя в Discovery",
        "mode": "BUILD", "long_term_direction": "NEEDS_REVIEW: уточнить долгосрочное направление у владельца",
        "success_criteria": ["NEEDS_REVIEW: согласовать наблюдаемый результат и критерии рабочего MVP"],
        "current_increment": "MVP", "increments": [{
            "id": "MVP", "outcome": "Минимальный полезный рабочий сценарий исходной цели",
            "check": "Проверить основной сценарий на реальном примере; критерии NEEDS_REVIEW",
            "extension_seam": "Выбрать минимальный интерфейс расширения после изучения системы",
            "not_now": "Не реализовывать будущую платформу до проверки текущего сценария"}],
        "metrics": [], "memory_refs": [{"path": ".project-master/VISION.md", "purpose": "исходная цель и решения владельца"},
            {"path": ".project-master/ROADMAP.md", "purpose": "текущий план инкремента"}],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--name")
    parser.add_argument("--idea", default="")
    parser.add_argument("--profile", choices=pm_state.LIFECYCLE_PROFILES, default="STANDARD",
                        help="STANDARD starts lean; FULL/CRITICAL add proportional design/review")
    parser.add_argument("--schema-version", choices=("2.1", "3.0"), default=VERSION,
                        help="2.1 only for compatibility fixtures; new projects should use 3.0")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--upgrade-plan", action="store_true")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.upgrade_plan:
            return upgrade_plan(args.root.resolve())
        return initialize(args.root, args.name or args.root.resolve().name, args.idea, args.profile, args.dry_run, args.schema_version)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
