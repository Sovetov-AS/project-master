#!/usr/bin/env python3
"""Audit repository-local Project Master memory and return CI-friendly status."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import state as pm_state  # noqa: E402
import traceability as pm_trace  # noqa: E402
import validate_bpmn as pm_bpmn  # noqa: E402

REQUIRED_FILES = (
    "STATE.yaml", "CURRENT_STATE.md", "VISION.md", "CONSTITUTION.md",
    "REQUIREMENTS.md", "ARCHITECTURE.md", "ROADMAP.md", "TRACEABILITY.md",
    "RISKS.md", "OPEN_QUESTIONS.md", "BUILD_LOG.md", "processes/INDEX.md",
    "processes/BPMN_GUIDE.md", "ROUTING.md", "state-events.jsonl",
)
REQUIRED_DIRS = (
    "processes/as-is", "processes/to-be", "processes/system", "decisions",
    "phases", "changes", "spikes", "reviews",
)
REQ_RE = re.compile(r"\bREQ-(?:F|NF|BR|SEC|INT)-\d{3}\b")
PROC_RE = re.compile(r"\b(?:PROC|PM)-\d{3}\b")
ADR_RE = re.compile(r"\bADR-\d{3}\b")
COMP_RE = re.compile(r"\bP\d{2}-C\d{2}\b")
STAGE_ORDER = {
    "NEW": 0, "DISCOVERY": 1, "SPECIFICATION": 2, "CONCEPT_REVIEW": 3,
    "PROCESS_MODELING": 4, "ARCHITECTURE": 5, "ARCHITECTURE_REVIEW": 6,
    "ROADMAP": 7, "ROADMAP_REVIEW": 8, "EXECUTION": 9,
    "VERIFICATION": 10, "COMPLETION_REVIEW": 11, "COMPLETE": 12,
}
CHANGE_PACKAGE_FILES = {
    "PROPOSAL.md", "REQUIREMENTS_DELTA.md", "PROCESS_DELTA.md",
    "IMPACT.md", "PLAN.md", "VERIFICATION.md",
}


def text_ids(path: Path, pattern: re.Pattern[str]) -> Set[str]:
    return set(pattern.findall(path.read_text(encoding="utf-8"))) if path.is_file() else set()


def component_identity(path: Path) -> Optional[str]:
    phase = re.match(r"(P\d{2})-", path.parent.parent.name)
    component = re.match(r"(C\d{2})-", path.name)
    return f"{phase.group(1)}-{component.group(1)}" if phase and component else None


def component_evidence_ok(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    section = re.search(r"(?ms)^## Completion evidence\s*$\n(.*?)(?=^## |\Z)", text)
    if not section:
        return False
    body = section.group(1)
    return bool(re.search(r"(?im)\bVERIFIED\b", body)) and not bool(re.search(r"(?im)Evidence:\s*(?:—|-|TBD)\s*$", body))


def audit(root: Path) -> Tuple[List[str], List[str]]:
    root = root.resolve()
    pm = root / ".project-master"
    errors: List[str] = []
    warnings: List[str] = []
    if not pm.is_dir():
        return [f"project memory missing: {pm}"], warnings
    for relative in REQUIRED_FILES:
        if not (pm / relative).is_file():
            errors.append(f"missing required file: {relative}")
    for relative in REQUIRED_DIRS:
        if not (pm / relative).is_dir():
            errors.append(f"missing required directory: {relative}")
    if errors and not (pm / "STATE.yaml").is_file():
        return errors, warnings
    try:
        data = pm_state.load_state(root)
        errors.extend(pm_state.validate_state(data))
        errors.extend(pm_state.approval_integrity_errors(root, data))
        errors.extend(pm_state.validate_event_log(root, data))
    except pm_state.StateError as exc:
        errors.append(str(exc))
        return errors, warnings
    if data.get("schema_version") != pm_state.VERSION:
        errors.append(f"unsupported schema_version: {data.get('schema_version')}; migration required")
    if data.get("project_master_version") != pm_state.VERSION:
        warnings.append(f"project_master_version is {data.get('project_master_version')}; engine is {pm_state.VERSION}")
    requirement_ids = text_ids(pm / "REQUIREMENTS.md", REQ_RE)
    process_ids: Set[str] = set()
    bpmn_by_stem = {path.stem: path for path in (pm / "processes").rglob("*.bpmn")}
    sidecar_by_stem = {path.stem: path for path in (pm / "processes").rglob("*.md") if path.name not in {"INDEX.md", "BPMN_GUIDE.md"}}
    for stem, path in sorted(bpmn_by_stem.items()):
        match = PROC_RE.search(stem)
        if match:
            process_ids.add(match.group(0))
        if stem not in sidecar_by_stem:
            errors.append(f"BPMN has no sidecar: {path.relative_to(pm)}")
        bpmn_errors, bpmn_warnings, _ = pm_bpmn.validate(path)
        errors.extend(f"{path.relative_to(pm)}: {item}" for item in bpmn_errors)
        warnings.extend(f"{path.relative_to(pm)}: {item}" for item in bpmn_warnings)
    for stem, path in sorted(sidecar_by_stem.items()):
        if stem not in bpmn_by_stem:
            errors.append(f"sidecar has no BPMN: {path.relative_to(pm)}")
    adr_ids = {match.group(0) for path in (pm / "decisions").glob("ADR-*.md") for match in [ADR_RE.search(path.name)] if match}
    component_ids: Set[str] = set()
    active_components: List[str] = []
    for path in (pm / "phases").glob("P*/components/C*.md"):
        identity = component_identity(path)
        if not identity:
            errors.append(f"invalid component path: {path.relative_to(pm)}")
            continue
        component_ids.add(identity)
        status = pm_state.component_status(path)
        if status == "ACTIVE":
            active_components.append(identity)
        if status == "COMPLETE" and not component_evidence_ok(path):
            errors.append(f"COMPLETE component has no VERIFIED evidence: {identity}")
    if len(active_components) > 1:
        errors.append(f"multiple ACTIVE components: {', '.join(sorted(active_components))}")
    state_active = data.get("active_component")
    if state_active and state_active not in component_ids:
        errors.append(f"STATE active_component does not exist: {state_active}")
    if state_active and active_components != [state_active]:
        errors.append(f"STATE/component ACTIVE mismatch: state={state_active}, files={active_components}")
    if not state_active and active_components:
        errors.append(f"component ACTIVE but STATE has none: {active_components[0]}")
    state_phase = data.get("active_phase")
    if state_phase:
        phase_matches = list((pm / "phases").glob(f"{state_phase}-*"))
        if len(phase_matches) != 1:
            errors.append(f"STATE active_phase is invalid: {state_phase}")
    for ref in data.get("relevant_requirements", []):
        if ref not in requirement_ids:
            errors.append(f"STATE references missing requirement: {ref}")
    for ref in data.get("relevant_processes", []):
        if ref not in process_ids:
            errors.append(f"STATE references missing process: {ref}")
    for ref in data.get("relevant_decisions", []):
        if ref not in adr_ids:
            errors.append(f"STATE references missing ADR: {ref}")
    stage = data.get("stage")
    order = STAGE_ORDER.get(data.get("resume_stage"), -1) if stage in pm_state.SIDE_STAGES else STAGE_ORDER.get(stage, -1)
    approval_thresholds = {"concept": 4, "processes": 5, "architecture": 7, "roadmap": 9}
    for approval, threshold in approval_thresholds.items():
        if order >= threshold and not data.get("approvals", {}).get(approval):
            errors.append(f"approval inconsistency: stage {stage} requires {approval}")
    if data.get("lifecycle_profile") in {"QUICK", "STANDARD"}:
        baseline = ("concept", "architecture", "roadmap")
        missing = [area for area in baseline if not data.get("approvals", {}).get(area)]
        if missing:
            errors.append(
                f"{data.get('lifecycle_profile')} profile requires approved baseline: {', '.join(missing)}"
            )
    change_ids: Set[str] = set()
    for package in sorted((pm / "changes").glob("CHG-*-*")):
        if not package.is_dir():
            continue
        match = re.match(r"(CHG-\d{3})-", package.name)
        if not match:
            errors.append(f"invalid change package name: {package.name}")
            continue
        change_ids.add(match.group(1))
        missing_files = sorted(name for name in CHANGE_PACKAGE_FILES if not (package / name).is_file())
        if missing_files:
            errors.append(f"incomplete change package {match.group(1)}: {', '.join(missing_files)}")
    active_change = data.get("active_change")
    if active_change and active_change not in change_ids:
        errors.append(f"STATE active_change does not exist: {active_change}")
    if stage == "EXECUTION" and not state_active:
        errors.append("EXECUTION requires exactly one ACTIVE component")
    if stage == "COMPLETE":
        if not data.get("approvals", {}).get("completion"):
            errors.append("COMPLETE without completion approval")
        verification = data.get("last_verification") or {}
        if verification.get("outcome") != "VERIFIED":
            errors.append("COMPLETE without VERIFIED project evidence")
        final_review = pm / "reviews" / "final-review.md"
        if not final_review.is_file():
            errors.append("COMPLETE without reviews/final-review.md")
    trace_errors, trace_warnings = pm_trace.validate(root)
    errors.extend(trace_errors)
    warnings.extend(trace_warnings)
    agents = root / "AGENTS.md"
    if not agents.is_file():
        warnings.append("root AGENTS.md is missing")
    else:
        content = agents.read_text(encoding="utf-8")
        if content.count("<!-- project-master:start -->") != 1 or content.count("<!-- project-master:end -->") != 1:
            errors.append("AGENTS.md managed section markers are missing or duplicated")
    if not errors and not warnings:
        warnings.append("no drift detected by structural validators; semantic audit still requires Codex review")
    return errors, warnings


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--strict", action="store_true", help="Treat warnings as CI failure")
    args = parser.parse_args(argv)
    try:
        errors, warnings = audit(args.root)
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    for error in errors:
        print(f"ERROR: {error}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        print(f"RESULT: ERROR ({len(errors)} errors, {len(warnings)} warnings)")
        return 1
    if warnings:
        print(f"RESULT: WARNING ({len(warnings)} warnings)")
        return 1 if args.strict else 0
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
