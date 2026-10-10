#!/usr/bin/env python3
"""Safe state-machine operations for Project Master 3.0 (2.1 compatible).

STATE.yaml is emitted as JSON-compatible YAML, allowing a dependency-free parser.
Legacy non-JSON YAML is never rewritten implicitly; create a migration plan first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import uuid
from contextlib import contextmanager
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

VERSION = "3.0"
SUPPORTED_SCHEMAS = {"2.1", "3.0"}
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
LIFECYCLE_PROFILES = ("QUICK", "STANDARD", "FULL", "CRITICAL")
ROUTING_MODES = ("native", "advisory", "delegated")
QUALITY_PROFILES = ("economy", "balanced", "maximum")
CAPABILITIES = ("mechanical", "balanced_reasoning", "deep_reasoning", "independent_review")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
GATES = {
    "PROCESS_MODELING": ("concept",),
    "ARCHITECTURE": ("concept", "processes"),
    "ROADMAP": ("architecture",),
    "EXECUTION": ("roadmap",),
    "COMPLETE": ("completion",),
}


class StateError(RuntimeError):
    pass


class StateData(dict):
    """An optimistic concurrency token, never serialized into project memory."""
    loaded_hash: Optional[str] = None


_locks: Dict[str, int] = {}


@contextmanager
def exclusive(root: Path):
    key = str(project_dir(root))
    if _locks.get(key) == threading.get_ident():
        yield
        return
    lock = project_dir(root) / "STATE.lock"
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise StateError("STATE writer active or stale STATE.lock; inspect owner, never overwrite") from exc
    _locks[key] = threading.get_ident()
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        _locks.pop(key, None)
        lock.unlink()


def serialized(function):
    @wraps(function)
    def wrapped(root, *args, **kwargs):
        with exclusive(root):
            return function(root, *args, **kwargs)
    return wrapped


def transitions(data: Dict[str, Any]) -> Dict[str, set]:
    result = {key: set(value) for key, value in PRIMARY_TRANSITIONS.items()}
    if data.get("schema_version") == "3.0":
        # Process modeling is optional; existing full paths remain supported.
        result["CONCEPT_REVIEW"].add("ARCHITECTURE")
        if data.get("lifecycle_profile") in {"QUICK", "STANDARD"}:
            result["SPECIFICATION"].add("ROADMAP")
        result["COMPLETE"].add("ROADMAP")  # a new increment, never a silent relaunch
    return result


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_dir(root: Path) -> Path:
    return root.resolve() / ".project-master"


def state_path(root: Path) -> Path:
    return project_dir(root) / "STATE.yaml"


def event_log_path(root: Path) -> Path:
    return project_dir(root) / "state-events.jsonl"


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
    result = StateData(data)
    result.loaded_hash = state_digest(data)
    return result


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


def state_digest(data: Dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def event_digest(event: Dict[str, Any]) -> str:
    payload = {key: value for key, value in event.items() if key != "event_hash"}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def append_event(root: Path, event_type: str, data: Dict[str, Any], payload: Optional[Dict[str, Any]] = None,
                 previous_state_hash: Optional[str] = None) -> None:
    path = event_log_path(root)
    previous_event_hash: Optional[str] = None
    if path.is_file():
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            try:
                previous_event = json.loads(lines[-1])
            except json.JSONDecodeError as exc:
                raise StateError(f"cannot append to invalid event log: {exc}") from exc
            previous_event_hash = previous_event.get("event_hash")
            if not previous_event_hash or previous_event_hash != event_digest(previous_event):
                raise StateError("cannot append to event log with an invalid hash chain")
    event = {
        "event_id": str(uuid.uuid4()),
        "at": now(),
        "type": event_type,
        "stage": data.get("stage"),
        "status": data.get("status"),
        "active_phase": data.get("active_phase"),
        "active_component": data.get("active_component"),
        "active_change": data.get("active_change"),
        "previous_state_hash": previous_state_hash,
        "previous_event_hash": previous_event_hash,
        "state_hash": state_digest(data),
        "payload": payload or {},
    }
    event["event_hash"] = event_digest(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def initialize_event_log(root: Path, data: Dict[str, Any]) -> None:
    path = event_log_path(root)
    if path.exists():
        raise StateError(f"refusing to overwrite event log: {path}")
    append_event(root, "project.initialized", data, {"project_id": data.get("project_id")})


def ensure_event_log_current(root: Path, data: Optional[Dict[str, Any]] = None) -> None:
    if (project_dir(root) / "pending-state.json").exists():
        raise StateError("unfinished state transaction; run state.py repair before mutation")
    errors = validate_event_log(root, data or load_state(root))
    if errors:
        raise StateError("refusing mutation: " + "; ".join(errors))


@serialized
def save_state(root: Path, data: Dict[str, Any], event_type: str = "state.updated",
               payload: Optional[Dict[str, Any]] = None,
               file_updates: Optional[Dict[Path, str]] = None) -> None:
    previous_hash: Optional[str] = None
    if state_path(root).is_file():
        previous_state = load_state(root)
        ensure_event_log_current(root, previous_state)
        previous_hash = state_digest(previous_state)
        expected = getattr(data, "loaded_hash", None)
        if expected is not None and expected != previous_hash:
            raise StateError("stale STATE revision; reload before mutation")
    data["updated_at"] = now()
    journal = project_dir(root) / "pending-state.json"
    transaction = {"previous_state_hash": previous_hash, "state": dict(data),
                   "event_type": event_type, "payload": payload or {}}
    updates = []
    for path, content in (file_updates or {}).items():
        resolved = path.resolve()
        if not resolved.is_relative_to(project_dir(root)) or not resolved.is_file():
            raise StateError("transaction artifact must be an existing project-memory file")
        updates.append({"path": str(resolved.relative_to(root.resolve())), "before": resolved.read_text(encoding="utf-8"), "after": content})
    transaction["files"] = updates
    transaction["sha256"] = state_digest(transaction)
    atomic_write(journal, json.dumps(transaction, ensure_ascii=False, indent=2) + "\n")
    for update in updates:
        atomic_write(root.resolve() / update["path"], update["after"])
    atomic_write(state_path(root), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    append_event(root, event_type, data, payload, previous_hash)
    update_current_state(root, data)
    journal.unlink()
    if isinstance(data, StateData):
        data.loaded_hash = state_digest(data)


@serialized
def repair(root: Path) -> None:
    """Finish only a known interrupted transaction; never accept arbitrary edits."""
    journal = project_dir(root) / "pending-state.json"
    if not journal.is_file():
        raise StateError("no pending transaction to repair")
    transaction = json.loads(journal.read_text(encoding="utf-8"))
    checksum = transaction.pop("sha256", None)
    if checksum != state_digest(transaction):
        raise StateError("pending transaction checksum mismatch")
    target = transaction["state"]
    current_hash = state_digest(load_state(root))
    target_hash = state_digest(target)
    old_hash = transaction["previous_state_hash"]
    if current_hash not in {target_hash, old_hash}:
        raise StateError("STATE diverged from pending transaction; reconcile saved backup")
    log = event_log_path(root).read_text(encoding="utf-8").splitlines()
    last = json.loads(log[-1])
    # Validate the complete chain against its last state without rebaselining it.
    check = target if last.get("state_hash") == target_hash else load_state(root)
    if last.get("state_hash") == old_hash:
        check = dict(check)
        # validation below checks chain separately from state for pre-write crash.
    errors = validate_event_log(root, check)
    errors = [item for item in errors if item.startswith("event log/state mismatch") is False]
    if errors or last.get("state_hash") not in {old_hash, target_hash}:
        raise StateError("event log diverged; cannot repair automatically")
    for update in transaction.get("files", []):
        path = (root.resolve() / update["path"]).resolve()
        if not path.is_relative_to(project_dir(root)) or not path.is_file() or path.read_text(encoding="utf-8") not in {update["before"], update["after"]}:
            raise StateError("transaction artifact diverged; reconcile backup")
    for update in transaction.get("files", []):
        atomic_write(root.resolve() / update["path"], update["after"])
    if last.get("state_hash") == old_hash:
        append_event(root, transaction["event_type"], target, transaction["payload"], old_hash)
    atomic_write(state_path(root), json.dumps(target, ensure_ascii=False, indent=2) + "\n")
    update_current_state(root, target)
    journal.unlink()


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
    if data.get("schema_version") == "3.0":
        text = "# CURRENT STATE — derived checkpoint, not a history log\n\n"
        text += "\n".join(f"{label}: {data.get(key) or '—'}" for label, key in (
            ("Project", "project_name"), ("Stage", "stage"), ("Status", "status"),
            ("Profile", "lifecycle_profile"), ("Phase", "active_phase"),
            ("Component", "active_component"), ("Change", "active_change")))
        text += "\n\nGoal, strategy, results, personal lessons: `private/MISSION.json`\n"
        text += "\n## Next action\n\n- " + str(data.get("next_action") or "—") + "\n"
        text += "\n## Last verification\n\n- " + json.dumps(data.get("last_verification"), ensure_ascii=False) + "\n"
        text += "\n## Blockers (scoped)\n\n" + json.dumps(data.get("blockers", []), ensure_ascii=False, indent=2) + "\n"
        text += "\nHistory: `state-events.jsonl`; existing narrative retained in the migration backup.\n"
        atomic_write(path, text)
        return
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = _replace_field(text, "Project", data.get("project_name"))
    text = _replace_field(text, "Stage", data.get("stage"))
    text = _replace_field(text, "Status", data.get("status"))
    text = _replace_field(text, "Profile", data.get("lifecycle_profile"))
    text = _replace_field(text, "Phase", data.get("active_phase"))
    text = _replace_field(text, "Component", data.get("active_component"))
    text = _replace_field(text, "Change", data.get("active_change"))
    routing = data.get("routing") or {}
    route_text = f"{routing.get('required_capability', '—')} / {routing.get('minimum_effort', '—')}"
    text = _replace_field(text, "Routing", route_text)
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
        "active_component", "active_process", "active_change", "approvals", "blockers",
        "next_action", "relevant_requirements", "relevant_processes",
        "relevant_decisions", "last_verification", "git_checkpoint_mode",
        "lifecycle_profile", "routing", "event_log",
    )
    for key in required:
        if key not in data:
            errors.append(f"missing field: {key}")
    stage = data.get("stage")
    if data.get("schema_version") not in SUPPORTED_SCHEMAS:
        errors.append("unsupported schema_version; explicit migration required")
    if stage not in STAGES:
        errors.append(f"unknown stage: {stage}")
    if stage == "COMPLETE" and data.get("active_component"):
        errors.append("COMPLETE requires no ACTIVE component")
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
    if data.get("lifecycle_profile") not in LIFECYCLE_PROFILES:
        errors.append(f"lifecycle_profile must be one of: {', '.join(LIFECYCLE_PROFILES)}")
    routing = data.get("routing")
    if not isinstance(routing, dict):
        errors.append("routing must be a mapping")
    else:
        if routing.get("mode") not in ROUTING_MODES:
            errors.append(f"routing.mode must be one of: {', '.join(ROUTING_MODES)}")
        if routing.get("quality_profile") not in QUALITY_PROFILES:
            errors.append(f"routing.quality_profile must be one of: {', '.join(QUALITY_PROFILES)}")
        if routing.get("required_capability") not in CAPABILITIES:
            errors.append(f"routing.required_capability must be one of: {', '.join(CAPABILITIES)}")
        if routing.get("minimum_effort") not in EFFORTS:
            errors.append(f"routing.minimum_effort must be one of: {', '.join(EFFORTS)}")
    if data.get("event_log") != ".project-master/state-events.jsonl":
        errors.append("event_log must point to .project-master/state-events.jsonl")
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
            historical = transitions({**data, "lifecycle_profile": "STANDARD"})
            if target not in historical.get(source, set()):
                errors.append(f"impossible transition in history: {source} -> {target}")
    return errors


def _normalized_approval_bytes(path: Path, area: str, version: str = "2.1") -> bytes:
    raw = path.read_bytes()
    if area != "roadmap" or path.suffix.lower() != ".md":
        return raw
    text = raw.decode("utf-8")
    text = re.sub(r"(?m)^Status:\s*`?[A-Z_]+`?\s*$", "Status: <MUTABLE>", text)
    text = re.sub(r"(?ms)^## Completion evidence\s*$.*?(?=^## |\Z)", "## Completion evidence\n<MUTABLE>\n", text)
    if version == "3.0":
        text = re.sub(r"(?im)\b(PLANNED|READY|ACTIVE|VERIFYING|VERIFIED|COMPLETE|SUPERSEDED|BLOCKED)\b(?=\s*\|)", "<PROGRESS>", text)
        text = re.sub(r"(?m)^(\s*[-*] )\[[ xX]\]", r"\1[<PROGRESS>]", text)
    return text.encode("utf-8")


def approval_artifacts(root: Path, area: str, version: str = "2.1") -> List[Path]:
    pm = project_dir(root)
    if area == "concept":
        candidates = [pm / name for name in ("VISION.md", "CONSTITUTION.md", "REQUIREMENTS.md", "RISKS.md", "OPEN_QUESTIONS.md")]
        if version == "3.0":
            candidates = [path for path in candidates if path.name not in {"RISKS.md", "OPEN_QUESTIONS.md"}]
    elif area == "processes":
        candidates = [pm / "processes" / "INDEX.md"]
        candidates += list((pm / "processes").rglob("*.bpmn"))
        candidates += [path for path in (pm / "processes").rglob("*.md") if path.name != "BPMN_GUIDE.md"]
    elif area == "architecture":
        candidates = [pm / "ARCHITECTURE.md"] + list((pm / "decisions").glob("ADR-*.md"))
    elif area == "roadmap":
        candidates = [pm / "ROADMAP.md"]
        if version == "3.0":
            candidates += [pm / "VISION.md", pm / "REQUIREMENTS.md"]
        candidates += list((pm / "phases").glob("P*/PLAN.md"))
        candidates += list((pm / "phases").glob("P*/components/C*.md"))
    elif area == "completion":
        candidates = [pm / "TRACEABILITY.md", pm / "reviews" / "final-review.md"]
    else:
        raise StateError(f"unknown approval: {area}")
    return sorted({path.resolve() for path in candidates if path.is_file()}, key=lambda item: str(item))


def approval_snapshot(root: Path, area: str, version: str = "2.1") -> Tuple[str, List[Dict[str, str]]]:
    pm = project_dir(root)
    items: List[Dict[str, str]] = []
    aggregate = hashlib.sha256()
    for path in approval_artifacts(root, area, version):
        relative = path.relative_to(pm).as_posix()
        digest = hashlib.sha256(_normalized_approval_bytes(path, area, version)).hexdigest()
        items.append({"path": relative, "sha256": digest})
        aggregate.update(relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
    if version == "3.0" and area == "processes":
        import workflow
        for path in sorted((pm / "workflows").glob("*.drawio")):
            contract = workflow.load_contract(path)
            digest = workflow.fingerprint(contract)
            relative = path.relative_to(pm).as_posix()
            items.append({"path": relative, "sha256": digest})
            aggregate.update(relative.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
    if version == "3.0" and area == "roadmap":
        import mission
        data = mission.load(root)
        definition = data["definition_history"][-1]["definition"]
        digest = mission.digest(definition)
        items.append({"path": "private/MISSION.json#definition", "sha256": digest})
        aggregate.update(b"private/MISSION.json#definition\0" + digest.encode("ascii") + b"\n")
    return aggregate.hexdigest(), items


def approval_integrity_errors(root: Path, data: Dict[str, Any], areas: Optional[Iterable[str]] = None) -> List[str]:
    errors: List[str] = []
    records = data.get("approval_records") or {}
    for area in areas or APPROVALS:
        if not data.get("approvals", {}).get(area):
            continue
        record = records.get(area)
        if not isinstance(record, dict) or not record.get("artifact_hash"):
            errors.append(f"approval {area} has no artifact hash; re-approval required")
            continue
        current_hash, _ = approval_snapshot(root, area, record.get("snapshot_version", "2.1"))
        if current_hash != record.get("artifact_hash"):
            errors.append(f"approval {area} is stale: approved artifacts changed")
    return errors


def validate_event_log(root: Path, data: Dict[str, Any]) -> List[str]:
    path = event_log_path(root)
    if not path.is_file():
        return [f"event log missing: {path}"]
    events: List[Dict[str, Any]] = []
    seen: set = set()
    previous_event_hash: Optional[str] = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            event = json.loads(raw)
        except json.JSONDecodeError as exc:
            return [f"event log line {number} is invalid JSON: {exc}"]
        if not isinstance(event, dict):
            return [f"event log line {number} must be a mapping"]
        event_id = event.get("event_id")
        if not event_id or event_id in seen:
            return [f"event log line {number} has missing or duplicate event_id"]
        if event.get("previous_event_hash") != previous_event_hash:
            return [f"event log hash chain is broken at line {number}"]
        if event.get("event_hash") != event_digest(event):
            return [f"event log event_hash is invalid at line {number}"]
        seen.add(event_id)
        events.append(event)
        previous_event_hash = event.get("event_hash")
    if not events:
        return ["event log is empty"]
    if events[0].get("type") != "project.initialized":
        return ["event log does not start with project.initialized"]
    if events[-1].get("state_hash") != state_digest(data):
        return ["event log/state mismatch: latest event does not describe current STATE"]
    return []


def missing_gate_approvals(root: Path, data: Dict[str, Any], target: str) -> List[str]:
    required = GATES.get(target, ())
    if data.get("schema_version") == "3.0":
        required = {**GATES, "ARCHITECTURE": ("concept",)}.get(target, ())
        if data.get("lifecycle_profile") in {"QUICK", "STANDARD"}:
            required = {"EXECUTION": ("roadmap",), "COMPLETE": ("completion",)}.get(target, ())
    missing = [name for name in required if not data.get("approvals", {}).get(name)]
    stale = {error.split()[1] for error in approval_integrity_errors(root, data, required)}
    return sorted(set(missing) | stale)


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


@serialized
def transition(root: Path, target: str, reason: str, next_action: Optional[str]) -> None:
    data = load_state(root)
    source = data.get("stage")
    if target not in STAGES:
        raise StateError(f"unknown target stage: {target}")
    if source in SIDE_STAGES:
        raise StateError(f"use resolve while state is {source}")
    if target in SIDE_STAGES:
        data["resume_stage"] = source
    elif target not in transitions(data).get(source, set()):
        raise StateError(f"transition forbidden: {source} -> {target}")
    missing = missing_gate_approvals(root, data, target)
    if missing:
        raise StateError(f"transition to {target} requires approvals: {', '.join(missing)}")
    if target == "EXECUTION" and not data.get("active_component"):
        raise StateError("EXECUTION requires one active component")
    if target == "COMPLETE":
        verification = data.get("last_verification") or {}
        if verification.get("outcome") != "VERIFIED":
            raise StateError("COMPLETE requires last_verification.outcome=VERIFIED")
        if data.get("active_component") or any(component_status(path) == "ACTIVE" for path in _component_files(root)):
            raise StateError("COMPLETE requires no ACTIVE component")
        errors = verification_errors(root, verification, data.get("schema_version") == "3.0")
        phase = data.get("active_phase")
        if phase:
            unfinished = [path.name for path in (find_phase(root, phase) / "components").glob("C*.md") if component_status(path) not in {"COMPLETE", "SUPERSEDED"}]
            if unfinished:
                errors.append("current phase has unfinished contracts: " + ", ".join(unfinished))
        if errors:
            raise StateError("; ".join(errors))
    data["stage"] = target
    data["status"] = "BLOCKED" if target == "BLOCKED" else (
        "WAITING_APPROVAL" if target.endswith("_REVIEW") else ("COMPLETE" if target == "COMPLETE" else "ACTIVE")
    )
    if target not in SIDE_STAGES:
        data["resume_stage"] = None
    if next_action:
        data["next_action"] = next_action
    data.setdefault("state_history", []).append({"from": source, "to": target, "at": now(), "reason": reason})
    save_state(root, data, "stage.transitioned", {"from": source, "to": target, "reason": reason})


@serialized
def approve(root: Path, area: str, source: str, revoke: bool = False) -> None:
    data = load_state(root)
    if area not in APPROVALS:
        raise StateError(f"unknown approval: {area}")
    value = not revoke
    if value and area == "completion" and not (project_dir(root) / "reviews" / "final-review.md").is_file():
        raise StateError("completion approval requires reviews/final-review.md")
    if value and area == "roadmap" and data.get("schema_version") == "3.0":
        import mission
        definition = mission.load(root)["definition_history"][-1]["definition"]
        if "NEEDS_REVIEW" in json.dumps(definition, ensure_ascii=False):
            raise StateError("clarify the mission's NEEDS_REVIEW goal/acceptance fields before plan approval")
    data["approvals"][area] = value
    if not source.strip():
        raise StateError("approval requires the actual owner decision source")
    version = data.get("schema_version", "2.1")
    artifact_hash, artifacts = approval_snapshot(root, area, version) if value else (None, [])
    if value and not artifacts:
        raise StateError("cannot approve an empty artifact set")
    data.setdefault("approval_records", {})[area] = {
        "approved": value, "at": now(), "source": source,
        "artifact_hash": artifact_hash, "artifacts": artifacts,
        "snapshot_version": version,
    }
    save_state(root, data, "approval.changed", {"area": area, "approved": value, "source": source})


@serialized
def set_profile(root: Path, profile: str, reason: str, source: str) -> None:
    data = load_state(root)
    if profile not in LIFECYCLE_PROFILES:
        raise StateError(f"unknown lifecycle profile: {profile}")
    if data.get("schema_version") != "3.0" and profile in {"QUICK", "STANDARD"}:
        baseline = ("concept", "architecture", "roadmap")
        missing = [area for area in baseline if not data.get("approvals", {}).get(area)]
        stale = approval_integrity_errors(root, data, baseline)
        if missing or stale:
            details = missing + stale
            raise StateError(
                f"{profile} requires an approved unchanged project baseline: {'; '.join(details)}"
            )
    old = data.get("lifecycle_profile")
    data["lifecycle_profile"] = profile
    data["profile_record"] = {"profile": profile, "at": now(), "source": source, "reason": reason}
    save_state(root, data, "profile.changed", {"from": old, "to": profile, "source": source, "reason": reason})


@serialized
def set_route(root: Path, mode: str, quality_profile: str, capability: str,
              effort: str, reason: str) -> None:
    if mode not in ROUTING_MODES:
        raise StateError(f"unknown routing mode: {mode}")
    if quality_profile not in QUALITY_PROFILES:
        raise StateError(f"unknown quality profile: {quality_profile}")
    if capability not in CAPABILITIES:
        raise StateError(f"unknown capability: {capability}")
    if effort not in EFFORTS:
        raise StateError(f"unknown effort: {effort}")
    data = load_state(root)
    proposed = {"mode": mode, "quality_profile": quality_profile,
                "required_capability": capability, "minimum_effort": effort, "reason": reason}
    if all((data.get("routing") or {}).get(key) == value for key, value in proposed.items()):
        return
    data["routing"] = {
        "mode": mode,
        "quality_profile": quality_profile,
        "required_capability": capability,
        "minimum_effort": effort,
        "reason": reason,
        "selected_at": now(),
    }
    save_state(root, data, "routing.selected", dict(data["routing"]))


@serialized
def set_active(root: Path, phase: str, component: str, next_action: Optional[str]) -> None:
    data = load_state(root)
    ensure_event_log_current(root, data)
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
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^Status:\s*`?[A-Z]+`?\s*$", "Status: ACTIVE", text, count=1)
    data["active_phase"] = phase
    data["active_component"] = component
    if next_action:
        data["next_action"] = next_action
    save_state(root, data, "component.activated", {"phase": phase, "component": component}, {path: text})


@serialized
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
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
    }
    save_state(root, data, "verification.recorded", {"outcome": outcome, "evidence": evidence, "method": method})


def verification_errors(root: Path, verification: Dict[str, Any], require_hash: bool = False) -> List[str]:
    reference = verification.get("evidence")
    if not isinstance(reference, str) or not reference:
        return ["verification evidence reference is missing"]
    path = (root.resolve() / reference).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return ["verification evidence changed or missing"]
    digest = verification.get("evidence_sha256")
    if require_hash and not digest:
        return ["3.0 completion requires a current hashed verification record; legacy flags are not fresh evidence"]
    if digest and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        return ["verification evidence changed or missing"]
    return []


@serialized
def complete_component(root: Path) -> None:
    data = load_state(root)
    ensure_event_log_current(root, data)
    component = data.get("active_component")
    phase = data.get("active_phase")
    verification = data.get("last_verification") or {}
    if not component or not phase:
        raise StateError("no active component")
    if verification.get("outcome") != "VERIFIED" or verification.get("component") != component:
        raise StateError("active component requires its own VERIFIED evidence")
    errors = verification_errors(root, verification, data.get("schema_version") == "3.0")
    if errors:
        raise StateError("; ".join(errors))
    if verification.get("evidence_sha256"):
        saved = (root.resolve() / verification["evidence"]).resolve()
        if not saved.is_relative_to(root.resolve()) or not saved.is_file() or hashlib.sha256(saved.read_bytes()).hexdigest() != verification["evidence_sha256"]:
            raise StateError("verification evidence changed or missing; verify again")
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
    text = evidence_pattern.sub(lambda match: match.group(1) + evidence_body, text, count=1)
    text = re.sub(r"(?m)^Status:\s*`?[A-Z]+`?\s*$", "Status: COMPLETE", text, count=1)
    data["last_completed_component"] = component
    data["active_component"] = None
    data["next_action"] = "Проверить фазу либо активировать следующий READY component."
    save_state(root, data, "component.completed", {"phase": phase, "component": component, "evidence": evidence}, {path: text})


@serialized
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
    save_state(root, data, "side_stage.resolved", {"from": source, "to": target, "reason": reason})


@serialized
def add_blocker(root: Path, reason: str, scope: str, resume_when: str, source: str,
                origin: str, basis: str, owner: str, next_action: Optional[str] = None):
    data = load_state(root)
    if data.get("schema_version") == "3.0" and not all(value.strip() for value in (scope, resume_when, source, basis, owner)):
        raise StateError("3.0 stop needs scope, resume-when, source, basis and owner; never invent a provider prohibition")
    data.setdefault("blockers", []).append({"reason": reason, "at": now(), "scope": scope,
        "resume_when": resume_when, "source": source, "origin": origin, "basis": basis, "owner": owner})
    save_state(root, data, "blocker.added", data["blockers"][-1])
    if scope == "project":
        transition(root, "BLOCKED", reason, next_action)


@serialized
def clear_blocker(root: Path, index: int, source: str):
    data = load_state(root)
    if index < 0 or index >= len(data.get("blockers", [])):
        raise StateError("blocker index out of range")
    if data.get("schema_version") == "3.0" and not source.strip():
        raise StateError("record why this scoped stop is actually resolved; removal is not new authority")
    removed = data["blockers"].pop(index)
    save_state(root, data, "blocker.cleared", {"index": index, "blocker": removed, "source": source})


def summary(data: Dict[str, Any]) -> str:
    verification = data.get("last_verification") or {}
    return "\n".join((
        f"PROJECT MASTER {VERSION} / memory {data.get('schema_version', 'unknown')}",
        f"Проект: {data.get('project_name', '—')}",
        f"Стадия: {data.get('stage', '—')} / {data.get('status', '—')}",
        f"Профиль: {data.get('lifecycle_profile') or '—'}",
        f"Активная фаза: {data.get('active_phase') or '—'}",
        f"Активный компонент: {data.get('active_component') or '—'}",
        f"Активное изменение: {data.get('active_change') or '—'}",
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
    sub.add_parser("repair")
    trans = sub.add_parser("transition")
    trans.add_argument("target", choices=STAGES)
    trans.add_argument("--reason", required=True)
    trans.add_argument("--next-action")
    approval = sub.add_parser("approve")
    approval.add_argument("area", choices=APPROVALS)
    approval.add_argument("--source", required=True)
    approval.add_argument("--revoke", action="store_true")
    profile = sub.add_parser("set-profile")
    profile.add_argument("profile", choices=LIFECYCLE_PROFILES)
    profile.add_argument("--reason", required=True)
    profile.add_argument("--source", required=True)
    route = sub.add_parser("route")
    route.add_argument("--mode", choices=ROUTING_MODES, default="advisory")
    route.add_argument("--quality-profile", choices=QUALITY_PROFILES, default="balanced")
    route.add_argument("--capability", choices=CAPABILITIES, required=True)
    route.add_argument("--effort", choices=EFFORTS, required=True)
    route.add_argument("--reason", required=True)
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
    block.add_argument("--scope", default="project", help="project or concrete blocked action/node; action-scoped stops do not block unrelated work")
    block.add_argument("--resume-when", default="")
    block.add_argument("--source", default="")
    block.add_argument("--basis", default="")
    block.add_argument("--owner", default="")
    block.add_argument("--origin", choices=("OWNER", "PROVIDER", "TOOL_POLICY", "PROJECT_DECISION", "HYPOTHESIS"), default="HYPOTHESIS")
    clear = sub.add_parser("clear-blocker")
    clear.add_argument("index", type=int)
    clear.add_argument("--source", default="")
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
            data = load_state(root)
            errors = validate_state(data)
            errors.extend(approval_integrity_errors(root, data))
            errors.extend(validate_event_log(root, data))
            if errors:
                for error in errors:
                    print(f"ERROR: {error}")
                return 1
            print("PASS: state is valid")
        elif args.command == "summary":
            print(summary(load_state(root)))
        elif args.command == "repair":
            repair(root)
            print("PASS: interrupted transaction repaired")
        elif args.command == "transition":
            transition(root, args.target, args.reason, args.next_action)
            print(summary(load_state(root)))
        elif args.command == "approve":
            approve(root, args.area, args.source, args.revoke)
            print(f"PASS: approval {args.area}={'false' if args.revoke else 'true'}")
        elif args.command == "set-profile":
            set_profile(root, args.profile, args.reason, args.source)
            print(summary(load_state(root)))
        elif args.command == "route":
            set_route(root, args.mode, args.quality_profile, args.capability, args.effort, args.reason)
            print("PASS: capability route recorded")
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
            add_blocker(root, args.reason, args.scope, args.resume_when, args.source, args.origin, args.basis, args.owner, args.next_action)
            print(summary(load_state(root)))
        elif args.command == "clear-blocker":
            clear_blocker(root, args.index, args.source)
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
