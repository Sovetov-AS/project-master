#!/usr/bin/env python3
"""Dependency-free BPMN 2.0 validation with optional local bpmnlint."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
REFERENCE_ATTRIBUTES = (
    "sourceRef", "targetRef", "attachedToRef", "processRef", "messageRef",
    "errorRef", "signalRef", "escalationRef", "calledElement",
)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def validate(path: Path) -> Tuple[List[str], List[str], Dict[str, int]]:
    errors: List[str] = []
    warnings: List[str] = []
    stats = {"elements": 0, "ids": 0, "sequence_flows": 0}
    if not path.is_file():
        return [f"file does not exist: {path}"], warnings, stats
    try:
        tree = ET.parse(str(path))
    except ET.ParseError as exc:
        return [f"XML is not well-formed: {exc}"], warnings, stats
    root = tree.getroot()
    if root.tag != f"{{{BPMN_NS}}}definitions":
        errors.append("root element must be BPMN 2.0 definitions with the standard namespace")
    elements = list(root.iter())
    stats["elements"] = len(elements)
    processes = root.findall(f".//{{{BPMN_NS}}}process")
    collaborations = root.findall(f".//{{{BPMN_NS}}}collaboration")
    if not processes and not collaborations:
        errors.append("definitions must contain a process or collaboration")
    id_map: Dict[str, ET.Element] = {}
    for element in elements:
        element_id = element.attrib.get("id")
        if not element_id:
            continue
        if element_id in id_map:
            errors.append(f"duplicate id: {element_id}")
        else:
            id_map[element_id] = element
    stats["ids"] = len(id_map)
    flow_nodes = {
        key for key, element in id_map.items()
        if local_name(element.tag) not in {"definitions", "process", "collaboration", "laneSet", "lane"}
    }
    sequence_flows = root.findall(f".//{{{BPMN_NS}}}sequenceFlow")
    stats["sequence_flows"] = len(sequence_flows)
    for flow in sequence_flows:
        flow_id = flow.attrib.get("id", "<missing-id>")
        source = flow.attrib.get("sourceRef")
        target = flow.attrib.get("targetRef")
        if not source or source not in id_map:
            errors.append(f"{flow_id}: broken sourceRef={source}")
        elif source not in flow_nodes:
            errors.append(f"{flow_id}: sourceRef is not a flow node: {source}")
        if not target or target not in id_map:
            errors.append(f"{flow_id}: broken targetRef={target}")
        elif target not in flow_nodes:
            errors.append(f"{flow_id}: targetRef is not a flow node: {target}")
    for element in elements:
        for child in list(element):
            if local_name(child.tag) in {"incoming", "outgoing"} and child.text and child.text.strip() not in id_map:
                errors.append(f"{element.attrib.get('id', local_name(element.tag))}: broken {local_name(child.tag)}={child.text.strip()}")
        for attribute in REFERENCE_ATTRIBUTES:
            reference = element.attrib.get(attribute)
            if reference and attribute != "calledElement" and reference not in id_map:
                # External message/error definitions may be omitted only if QName-qualified.
                if ":" not in reference:
                    errors.append(f"{element.attrib.get('id', local_name(element.tag))}: broken {attribute}={reference}")
    if not sequence_flows and processes:
        warnings.append("process contains no sequenceFlow")
    if not root.findall(".//{http://www.omg.org/spec/BPMN/20100524/DI}BPMNDiagram"):
        warnings.append("BPMN DI/layout is absent; visual editors may auto-layout the diagram")
    return errors, warnings, stats


def find_bpmnlint(path: Path) -> Optional[str]:
    for base in (path.parent, *path.parents):
        candidate = base / "node_modules" / ".bin" / "bpmnlint"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("bpmnlint")


def semantic_lint(path: Path) -> Tuple[str, str]:
    executable = find_bpmnlint(path)
    if not executable:
        return "unavailable", "SEMANTIC LINT NOT AVAILABLE"
    with tempfile.TemporaryDirectory(prefix="project-master-bpmnlint-") as directory:
        config = Path(directory) / ".bpmnlintrc"
        config.write_text('{"extends": "bpmnlint:recommended"}\n', encoding="utf-8")
        completed = subprocess.run(
            [executable, "--config", str(config), str(path)],
            text=True, capture_output=True, check=False,
        )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode == 0:
        return "passed", "SEMANTIC LINT PASSED" + (f"\n{output}" if output else "")
    return "failed", "SEMANTIC LINT FAILED" + (f"\n{output}" if output else "")


def sync_status(path: Path, sidecar: Optional[Path]) -> Tuple[str, Optional[str]]:
    if sidecar is None:
        return "not_checked", None
    if not sidecar.is_file():
        return "error", f"sync sidecar does not exist: {sidecar}"
    content = sidecar.read_text(encoding="utf-8")
    match = re.search(r"(?im)^-?\s*SHA-256:\s*`?([0-9a-f]{64})`?\s*$", content)
    current = hashlib.sha256(path.read_bytes()).hexdigest()
    if not match:
        return "unknown_baseline", f"SYNC BASELINE NOT FOUND; current SHA-256={current}"
    previous = match.group(1).lower()
    if previous == current:
        return "unchanged", f"SYNC UNCHANGED: SHA-256={current}"
    return "changed", f"SYNC CHANGE DETECTED: previous={previous} current={current}"


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-semantic", action="store_true")
    parser.add_argument("--check-sync", type=Path, metavar="SIDECAR")
    args = parser.parse_args(argv)
    errors, warnings, stats = validate(args.file.resolve())
    lint_status, lint_output = ("skipped", "SEMANTIC LINT SKIPPED") if args.no_semantic else semantic_lint(args.file.resolve())
    sync_state, sync_output = sync_status(args.file.resolve(), args.check_sync.resolve() if args.check_sync else None)
    if args.json:
        print(json.dumps({
            "basic": "passed" if not errors else "failed", "errors": errors,
            "warnings": warnings, "stats": stats, "semantic": lint_status,
            "sync": sync_state,
        }, ensure_ascii=False, indent=2))
    else:
        for error in errors:
            print(f"ERROR: {error}")
        for warning in warnings:
            print(f"WARNING: {warning}")
        if not errors:
            print("BASIC VALIDATION PASSED")
        print(lint_output)
        if sync_output:
            print(sync_output)
    return 1 if errors or lint_status == "failed" or sync_state == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
