#!/usr/bin/env python3
"""Safe state-machine operations for Project Master 2.0.

STATE.yaml is emitted as JSON-compatible YAML, allowing a dependency-free parser.
Legacy non-JSON YAML is never rewritten implicitly; create a migration plan first.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "2.0"
STAGES = (
    "NEW", "DISCOVERY", "SPECIFICATION", "CONCEPT_REVIEW",
    "PROCESS_MODELING", "ARCHITECTURE", "ARCHITECTURE_REVIEW",
    "ROADMAP", "ROADMAP_REVIEW", "EXECUTION", "VERIFICATION",
    "BLOCKED", "CHANGE_REVIEW", "COMPLETION_REVIEW", "COMPLETE",
)
PRIMARY_TRANSITIONS = {
    "NEW": {"DISCOVERY"},
    "DISCOVERY": {"SPECIFICATION"},
    "SPECIFICATION": {"CONCEPT_REVIEW"},
    "CONCEPT_REVIEW": {"PROCESS_MODELING"},
    "PROCESS_MODELING": {"ARCHITECTURE"},
    "ARCHITECTURE": {"ARCHITECTURE_REVIEW"},
    "ARCHITECTURE_REVIEW": {"ROADMAP"},
    "ROADMAP": {"ROADMAP_REVIEW"},
    "ROADMAP_REVIEW": {"EXECUTION"},
    "EXECUTION": {"VERIFICATION"},
    "VERIFICATION": {"EXECUTION", "COMPLETION_REVIEW"},
    "COMPLETION_REVIEW": {"COMPLETE"},
    "COMPLETE": set(),
}
SIDE_STAGES = {"BLOCKED", "CHANGE_REVIEW"}
APPROVALS = ("concept", "processes", "architecture", "roadmap", "completion")
GATES = {
    "PROCESS_MODELING": ("concept",),
    "ARCHITECTURE": ("concept", "processes"),
    "ROADMAP": ("architecture",),
    "EXECUTION": ("roadmap",),
    "COMPLETE": ("completion",),
}


class StateError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_dir(root: Path) -> Path:
    return root.resolve() / ".project-master"


def state_path(root: Path) -> Path:
    return project_dir(root) / "STATE.yaml"


def load_state(root: Path) -> Dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        raise StateError(f"STATE not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(
            f"STATE.yaml is not JSON-compatible YAML ({exc}). "
            "Do not rewrite it implicitly; create a migration plan."
        ) from exc
    if not isinstance(data, dict):
        raise StateError("STATE.yaml root must be a mapping")
    return data


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_state(root: Path, data: Dict[str, Any]) -> None:
    data["updated_at"] = now()
    atomic_write(state_path(root), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    update_current_state(root, data)


def _replace_field(text: str, label: str, value: Any) -> str:
    rendered = "—" if value in (None, "", []) else str(value)
    pattern = re.compile(rf"(?m)^{re.escape(label)}:.*$")
    replacement = f"{label}: {rendered}"
    return pattern.sub(replacement, text, count=1) if pattern.search(text) else text


def _replace_first_bullet(text: str, heading: str, value: Any) -> str:
    rendered = "—" if value in (None, "", []) else str(value)
    pattern = re.compile(rf"(?ms)^(## {re.escape(heading)}\n\n)- .*?(?=\n\n## |\Z)")
    return pattern.sub(rf"\1- {rendered}", text, count=1) if pattern.search(text) else text


def update_current_state(root: Path, data: Dict[str, Any]) -> None:
    path = project_dir(root) / "CURRENT_STATE.md"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = _replace_field(text, "Project", data.get("project_name"))
    text = _replace_field(text, "Stage", data.get("stage"))
    text = _replace_field(text, "Status", data.get("status"))
    text = _replace_field(text, "Phase", data.get("active_phase"))
    text = _replace_field(text, "Component", data.get("active_component"))
    text = _replace_first_bullet(text, "Next action", data.get("next_action"))
    verification = data.get("last_verification")
    if isinstance(verification, dict):
        verification = f"{verification.get('outcome')}: {verification.get('evidence', '—')}"
    text = _replace_first_bullet(text, "Last verification", verification)
    atomic_write(path, text)


def validate_state(data: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    required = (
        "schema_version", "project_master_version", "project_id", "project_name",
        "created_at", "updated_at", "stage", "status", "active_phase",
        "active_component", "active_process", "approvals", "blockers",
        "next_action", "relevant_requirements", "relevant_processes",
        "relevant_decisions", "last_verification", "git_checkpoint_mode",
    )
    for key in required:
        if key not in data:
            errors.append(f"missing field: {key}")
    stage = data.get("stage")
    if stage not in STAGES:
        errors.append(f"unknown stage: {stage}")
    approvals = data.get("approvals")
    if not isinstance(approvals, dict):
        errors.append("approvals must be a mapping")
    else:
        for key in APPROVALS:
            if not isinstance(approvals.get(key), bool):
                errors.append(f"approval {key} must be boolean")
    for key in ("blockers", "relevant_requirements", "relevant_processes", "relevant_decisions"):
        if key in data and not isinstance(data[key], list):
            errors.append(f"{key} must be a list")
    if data.get("git_checkpoint_mode") not in {"manual", "ask", "auto"}:
        errors.append("git_checkpoint_mode must be manual, ask, or auto")
    if stage == "BLOCKED" and not data.get("blockers"):
        errors.append("BLOCKED requires at least one blocker")
    if stage in SIDE_STAGES and data.get("resume_stage") not in PRIMARY_TRANSITIONS:
        errors.append(f"{stage} requires a valid resume_stage")
    history = data.get("state_history", [])
    if not isinstance(history, list):
        errors.append("state_history must be a list")
    else:
        for index, item in enumerate(history):
            if not isinstance(item, dict):
                errors.append(f"state_history[{index}] must be a mapping")
                continue
            source, target = item.get("from"), item.get("to")
            if target in SIDE_STAGES or source in SIDE_STAGES:
                continue
            if target not in PRIMARY_TRANSITIONS.get(source, set()):
                errors.append(f"impossible transition in history: {source} -> {target}")
    return errors


def missing_gate_approvals(data: Dict[str, Any], target: str) -> List[str]:
    return [name for name in GATES.get(target, ()) if not data.get("approvals", {}).get(name)]


def _component_files(root: Path) -> Iterable[Path]:
    phases = project_dir(root) / "phases"
    return phases.glob("P*/components/C*.md") if phases.is_dir() else ()


def component_status(path: Path) -> Optional[str]:
    match = re.search(r"(?m)^Status:\s*`?([A-Z]+)`?\s*$", path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def set_component_status(path: Path, status: str) -> None:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r"(?m)^Status:\s*`?[A-Z]+`?\s*$")
    if not pattern.search(text):
        raise StateError(f"component has no Status field: {path}")
    atomic_write(path, pattern.sub(f"Status: {status}", text, count=1))


def find_phase(root: Path, phase_id: str) -> Path:
    matches = list((project_dir(root) / "phases").glob(f"{phase_id}-*"))
    if len(matches) != 1 or not matches[0].is_dir():
        raise StateError(f"expected exactly one phase directory for {phase_id}")
    return matches[0]


def find_component(root: Path, phase_id: str, component_id: str) -> Path:
    if not component_id.startswith(phase_id + "-C"):
        raise StateError(f"component {component_id} does not belong to {phase_id}")
    local_id = component_id.split("-", 1)[1]
    matches = list((find_phase(root, phase_id) / "components").glob(f"{local_id}-*.md"))
    if len(matches) != 1:
        raise StateError(f"expected exactly one component file for {component_id}")
    return matches[0]


def transition(root: Path, target: str, reason: str, next_action: Optional[str]) -> None:
    data = load_state(root)
    source = data.get("stage")
    if target not in STAGES:
        raise StateError(f"unknown target stage: {target}")
    if source in SIDE_STAGES:
        raise StateError(f"use resolve while state is {source}")
    if target in SIDE_STAGES:
        data["resume_stage"] = source
    elif target not in PRIMARY_TRANSITIONS.get(source, set()):
        raise StateError(f"transition forbidden: {source} -> {target}")
    missing = missing_gate_approvals(data, target)
    if missing:
        raise StateError(f"transition to {target} requires approvals: {', '.join(missing)}")
    if target == "EXECUTION" and not data.get("active_component"):
        raise StateError("EXECUTION requires one active component")
    if target == "COMPLETE":
        verification = data.get("last_verification") or {}
        if verification.get("outcome") != "VERIFIED":
            raise StateError("COMPLETE requires last_verification.outcome=VERIFIED")
    data["stage"] = target
    data["status"] = "BLOCKED" if target == "BLOCKED" else (
        "WAITING_APPROVAL" if target.endswith("_REVIEW") else ("COMPLETE" if target == "COMPLETE" else "ACTIVE")
    )
    if target not in SIDE_STAGES:
        data["resume_stage"] = None
    if next_action:
        data["next_action"] = next_action
    data.setdefault("state_history", []).append({"from": source, "to": target, "at": now(), "reason": reason})
    save_state(root, data)


def approve(root: Path, area: str, source: str, revoke: bool = False) -> None:
    data = load_state(root)
    if area not in APPROVALS:
        raise StateError(f"unknown approval: {area}")
    value = not revoke
    data["approvals"][area] = value
    data.setdefault("approval_records", {})[area] = {
        "approved": value, "at": now(), "source": source,
    }
    save_state(root, data)


def set_active(root: Path, phase: str, component: str, next_action: Optional[str]) -> None:
    data = load_state(root)
    path = find_component(root, phase, component)
    active_files = [candidate for candidate in _component_files(root) if component_status(candidate) == "ACTIVE"]
    if active_files and path not in active_files:
        raise StateError(f"another ACTIVE component exists: {active_files[0]}")
    old = data.get("active_component")
    if old and old != component:
        old_path = find_component(root, data.get("active_phase"), old)
        if component_status(old_path) not in {"COMPLETE", "SUPERSEDED"}:
            raise StateError(f"current component {old} is not COMPLETE or SUPERSEDED")
    status = component_status(path)
    if status not in {"READY", "ACTIVE"}:
        raise StateError(f"component must be READY before activation, got {status}")
    set_component_status(path, "ACTIVE")
    data["active_phase"] = phase
    data["active_component"] = component
    if next_action:
        data["next_action"] = next_action
    save_state(root, data)


def record_verification(root: Path, outcome: str, evidence: str, method: str) -> None:
    data = load_state(root)
    if outcome not in {"VERIFIED", "PARTIALLY_VERIFIED", "NOT_VERIFIED"}:
        raise StateError("invalid verification outcome")
    evidence_path = (root.resolve() / evidence).resolve()
    try:
        evidence_path.relative_to(root.resolve())
    except ValueError as exc:
        raise StateError("evidence path must be inside project root") from exc
    if not evidence_path.is_file():
        raise StateError(f"evidence file does not exist: {evidence}")
    data["last_verification"] = {
        "outcome": outcome, "evidence": evidence, "method": method, "at": now(),
        "component": data.get("active_component"), "phase": data.get("active_phase"),
    }
    save_state(root, data)


def complete_component(root: Path) -> None:
    data = load_state(root)
    component = data.get("active_component")
    phase = data.get("active_phase")
    verification = data.get("last_verification") or {}
    if not component or not phase:
        raise StateError("no active component")
    if verification.get("outcome") != "VERIFIED" or verification.get("component") != component:
        raise StateError("active component requires its own VERIFIED evidence")
    path = find_component(root, phase, component)
    text = path.read_text(encoding="utf-8")
    evidence = verification.get("evidence", "—")
    evidence_pattern = re.compile(r"(?ms)(^## Completion evidence\s*$\n)(.*?)(?=^## |\Z)")
    if not evidence_pattern.search(text):
        raise StateError(f"component has no Completion evidence section: {path}")
    evidence_body = (
        f"\n- Status: VERIFIED\n- Evidence: `{evidence}`\n"
        f"- Method: {verification.get('method', '—')}\n- Verified at: {verification.get('at', now())}\n\n"
    )
    atomic_write(path, evidence_pattern.sub(lambda match: match.group(1) + evidence_body, text, count=1))
    set_component_status(path, "COMPLETE")
    data["last_completed_component"] = component
    data["active_component"] = None
    data["next_action"] = "Проверить фазу либо активировать следующий READY component."
    save_state(root, data)


def resolve(root: Path, reason: str, next_action: Optional[str]) -> None:
    data = load_state(root)
    source = data.get("stage")
    target = data.get("resume_stage")
    if source not in SIDE_STAGES or target not in PRIMARY_TRANSITIONS:
        raise StateError("resolve is only valid for BLOCKED or CHANGE_REVIEW with resume_stage")
    if source == "BLOCKED" and data.get("blockers"):
        raise StateError("clear blockers before resolve")
    data["stage"] = target
    data["status"] = "ACTIVE"
    data["resume_stage"] = None
    if next_action:
        data["next_action"] = next_action
    data.setdefault("state_history", []).append({"from": source, "to": target, "at": now(), "reason": reason})
    save_state(root, data)


def summary(data: Dict[str, Any]) -> str:
    verification = data.get("last_verification") or {}
    return "\n".join((
        "PROJECT MASTER 2.0",
        f"Проект: {data.get('project_name', '—')}",
        f"Стадия: {data.get('stage', '—')} / {data.get('status', '—')}",
        f"Активная фаза: {data.get('active_phase') or '—'}",
        f"Активный компонент: {data.get('active_component') or '—'}",
        f"Готово: {data.get('last_completed_component') or '—'}",
        f"Сейчас: {verification.get('outcome') or '—'}",
        f"Следующий шаг: {data.get('next_action') or '—'}",
        f"Требуется решение пользователя: {'да' if data.get('status') == 'WAITING_APPROVAL' else 'нет'}",
    ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    sub.add_parser("validate")
    sub.add_parser("summary")
    trans = sub.add_parser("transition")
    trans.add_argument("target", choices=STAGES)
    trans.add_argument("--reason", required=True)
    trans.add_argument("--next-action")
    approval = sub.add_parser("approve")
    approval.add_argument("area", choices=APPROVALS)
    approval.add_argument("--source", required=True)
    approval.add_argument("--revoke", action="store_true")
    active = sub.add_parser("set-active")
    active.add_argument("phase")
    active.add_argument("component")
    active.add_argument("--next-action")
    verify = sub.add_parser("record-verification")
    verify.add_argument("outcome", choices=("VERIFIED", "PARTIALLY_VERIFIED", "NOT_VERIFIED"))
    verify.add_argument("--evidence", required=True)
    verify.add_argument("--method", required=True)
    sub.add_parser("complete-component")
    block = sub.add_parser("block")
    block.add_argument("reason")
    block.add_argument("--next-action")
    clear = sub.add_parser("clear-blocker")
    clear.add_argument("index", type=int)
    resolve_parser = sub.add_parser("resolve")
    resolve_parser.add_argument("--reason", required=True)
    resolve_parser.add_argument("--next-action")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "show":
            print(json.dumps(load_state(root), ensure_ascii=False, indent=2))
        elif args.command == "validate":
            errors = validate_state(load_state(root))
            if errors:
                for error in errors:
                    print(f"ERROR: {error}")
                return 1
            print("PASS: state is valid")
        elif args.command == "summary":
            print(summary(load_state(root)))
        elif args.command == "transition":
            transition(root, args.target, args.reason, args.next_action)
            print(summary(load_state(root)))
        elif args.command == "approve":
            approve(root, args.area, args.source, args.revoke)
            print(f"PASS: approval {args.area}={'false' if args.revoke else 'true'}")
        elif args.command == "set-active":
            set_active(root, args.phase, args.component, args.next_action)
            print(summary(load_state(root)))
        elif args.command == "record-verification":
            record_verification(root, args.outcome, args.evidence, args.method)
            print("PASS: verification recorded")
        elif args.command == "complete-component":
            complete_component(root)
            print(summary(load_state(root)))
        elif args.command == "block":
            data = load_state(root)
            data.setdefault("blockers", []).append({"reason": args.reason, "at": now()})
            save_state(root, data)
            transition(root, "BLOCKED", args.reason, args.next_action)
            print(summary(load_state(root)))
        elif args.command == "clear-blocker":
            data = load_state(root)
            if args.index < 0 or args.index >= len(data.get("blockers", [])):
                raise StateError("blocker index out of range")
            data["blockers"].pop(args.index)
            save_state(root, data)
            print("PASS: blocker cleared")
        elif args.command == "resolve":
            resolve(root, args.reason, args.next_action)
            print(summary(load_state(root)))
        return 0
    except StateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
