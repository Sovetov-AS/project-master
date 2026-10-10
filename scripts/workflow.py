#!/usr/bin/env python3
"""Read-only validation and comparison of editable product interaction maps.

The .drawio file is the contract source, not an executable orchestration engine.
Only explicitly managed cells participate in the contract. No third-party modules.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import unquote
from xml.etree import ElementTree as ET

MAX_BYTES = 4 * 1024 * 1024
KINDS = {"trigger", "skill", "component", "gate", "external", "outcome"}
STATUSES = {"PLANNED", "IMPLEMENTED", "VERIFIED"}
STOP_TYPES = {"AUTHORIZATION", "INPUT", "MISMATCH", "UNCERTAINTY", "PROVIDER", "RUNTIME_FAILURE"}
ORIGINS = {"OWNER", "PROVIDER", "TOOL_POLICY", "PROJECT_DECISION", "HYPOTHESIS"}
TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


class WorkflowError(ValueError):
    pass


def parse_xml(raw: bytes) -> ET.Element:
    if len(raw) > MAX_BYTES:
        raise WorkflowError("XML exceeds the 4 MiB limit")
    declarations = raw.upper().replace(b"\x00", b"")
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise WorkflowError("DTD/entity declarations are not supported")
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise WorkflowError(f"invalid XML: {exc}") from exc


def decode_page(page: ET.Element) -> ET.Element:
    model = page.find("mxGraphModel")
    if model is not None:
        return model
    payload = (page.text or "").strip()
    if not payload:
        raise WorkflowError("diagram has no mxGraphModel or compressed content")
    try:
        compressed = base64.b64decode(payload, validate=True)
        decompressor = zlib.decompressobj(-15)
        inflated = decompressor.decompress(compressed, MAX_BYTES + 1)
        if len(inflated) > MAX_BYTES or decompressor.unconsumed_tail:
            raise WorkflowError("compressed diagram exceeds the 4 MiB limit")
        if not decompressor.eof or decompressor.unused_data:
            raise WorkflowError("invalid compressed diagram stream")
        text = unquote(inflated.decode("utf-8"), errors="strict")
        model = parse_xml(text.encode("utf-8"))
    except (ValueError, UnicodeError, zlib.error) as exc:
        if isinstance(exc, WorkflowError):
            raise
        raise WorkflowError(f"cannot decode compressed diagram: {exc}") from exc
    if model.tag != "mxGraphModel":
        raise WorkflowError("compressed page must contain mxGraphModel")
    return model


def load_contract(path: Path, page_id: Optional[str] = None) -> Dict[str, Any]:
    with path.open("rb") as handle:
        document = parse_xml(handle.read(MAX_BYTES + 1))
    if document.tag == "mxGraphModel":
        if page_id:
            raise WorkflowError("bare mxGraphModel has no page IDs")
        model = document
        selected_id = "page-1"
    elif document.tag == "mxfile":
        pages = document.findall("diagram")
        ids = [page.get("id") for page in pages]
        if not pages or any(not value for value in ids) or len(ids) != len(set(ids)):
            raise WorkflowError("diagram page IDs must be present and unique")
        selected = [page for page in pages if page.get("id") == page_id] if page_id else pages
        if len(selected) != 1:
            raise WorkflowError("select exactly one page with --page ID; available: " + ", ".join(ids))
        model = decode_page(selected[0])
        selected_id = selected[0].get("id")
    else:
        raise WorkflowError("expected mxfile or mxGraphModel")
    graph_root = model.find("root")
    if graph_root is None:
        raise WorkflowError("mxGraphModel/root is missing")
    all_ids: Set[str] = set()
    nodes: Dict[str, Any] = {}
    edges: Dict[str, Any] = {}
    unmanaged_edges: List[Dict[str, Any]] = []
    for wrapper in graph_root:
        cell = wrapper if wrapper.tag == "mxCell" else wrapper.find("mxCell")
        if cell is None:
            raise WorkflowError(f"unsupported graph element: {wrapper.tag}")
        identity = wrapper.get("id") or cell.get("id")
        if not identity or identity in all_ids:
            raise WorkflowError(f"missing or duplicate cell ID: {identity}")
        all_ids.add(identity)
        attributes = dict(cell.attrib)
        attributes.update(wrapper.attrib)
        kind = attributes.get("pm_kind")
        is_vertex = cell.get("vertex") == "1"
        is_edge = cell.get("edge") == "1"
        if is_vertex and is_edge:
            raise WorkflowError(f"{identity}: cell cannot be both vertex and edge")
        contract = {key: value for key, value in attributes.items() if key.startswith("pm_")}
        contract["id"] = identity
        if kind:
            # Human label edits are semantic; geometry/styles never are.
            contract["label"] = attributes.get("label", attributes.get("value", ""))
            if kind == "transition":
                if not is_edge:
                    raise WorkflowError(f"{identity}: transition must be an edge")
                contract["source"] = cell.get("source", "")
                contract["target"] = cell.get("target", "")
                edges[identity] = contract
            elif kind in KINDS:
                if not is_vertex:
                    raise WorkflowError(f"{identity}: {kind} must be a vertex")
                nodes[identity] = contract
            else:
                raise WorkflowError(f"{identity}: unknown pm_kind: {kind}")
        elif is_edge:
            unmanaged_edges.append({"id": identity, "source": cell.get("source"), "target": cell.get("target")})
    if "0" not in all_ids or "1" not in all_ids:
        raise WorkflowError("structural cells 0 and 1 are required")
    return {"page": selected_id, "nodes": nodes, "edges": edges, "unmanaged_edges": unmanaged_edges}


def tokens(value: str, identity: str, field: str, errors: List[str]) -> Set[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if len(items) != len(set(items)) or any(not TOKEN.fullmatch(item) for item in items):
        errors.append(f"{identity}: {field} must contain unique comma-separated identifiers")
    return set(items)


def reachable(starts: Set[str], adjacency: Dict[str, Set[str]], excluded: Optional[Set[str]] = None) -> Set[str]:
    excluded = excluded or set()
    visited: Set[str] = set()
    pending = list(starts - excluded)
    while pending:
        current = pending.pop()
        if current in visited or current in excluded:
            continue
        visited.add(current)
        pending.extend(adjacency.get(current, set()) - visited - excluded)
    return visited


def has_cycle(adjacency: Dict[str, Set[str]]) -> bool:
    indegrees = {identity: 0 for identity in adjacency}
    for targets in adjacency.values():
        for target in targets:
            indegrees[target] += 1
    pending = [identity for identity, degree in indegrees.items() if not degree]
    processed = 0
    while pending:
        current = pending.pop()
        processed += 1
        for target in adjacency[current]:
            indegrees[target] -= 1
            if not indegrees[target]:
                pending.append(target)
    return processed != len(indegrees)


def check_reference(value: str, root: Path, identity: str, errors: List[str]) -> None:
    path = Path(value)
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        errors.append(f"{identity}: reference escapes project root: {value}")
        return
    if path.is_absolute():
        errors.append(f"{identity}: use project-relative references: {value}")
    elif not resolved.is_file():
        errors.append(f"{identity}: missing reference: {value}")


def validate(contract: Dict[str, Any], root: Optional[Path] = None) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    nodes, edges = contract["nodes"], contract["edges"]
    if not nodes:
        return ["no managed product nodes (pm_kind)"], warnings
    adjacency: Dict[str, Set[str]] = {identity: set() for identity in nodes}
    reverse: Dict[str, Set[str]] = {identity: set() for identity in nodes}
    unbounded: Dict[str, Set[str]] = {identity: set() for identity in nodes}
    incoming: Dict[str, Set[str]] = {identity: set() for identity in nodes}
    outgoing: Dict[str, List[Dict[str, Any]]] = {identity: [] for identity in nodes}
    inputs, outputs = {}, {}
    root = root.resolve() if root else None
    for identity, node in nodes.items():
        inputs[identity] = tokens(node.get("pm_inputs", ""), identity, "pm_inputs", errors)
        outputs[identity] = tokens(node.get("pm_outputs", ""), identity, "pm_outputs", errors)
        if not node.get("pm_name", "").strip():
            errors.append(f"{identity}: pm_name is required")
        status = node.get("pm_status")
        if status not in STATUSES:
            errors.append(f"{identity}: pm_status must be PLANNED, IMPLEMENTED or VERIFIED")
        if node["pm_kind"] in {"skill", "component", "external"} and not node.get("pm_handler", "").strip():
            errors.append(f"{identity}: pm_handler must identify the responsible skill/component/provider")
        implementation = node.get("pm_implementation", "").strip()
        evidence = [item.strip() for item in node.get("pm_evidence", "").split(";") if item.strip()]
        if status in {"IMPLEMENTED", "VERIFIED"} and node["pm_kind"] in {"skill", "component", "external"} and not implementation:
            errors.append(f"{identity}: implemented node requires pm_implementation")
        if status == "VERIFIED" and not evidence:
            errors.append(f"{identity}: VERIFIED requires pm_evidence; drawing is not evidence")
        references = ([implementation] if implementation else []) + evidence
        if references and root:
            for reference in references:
                check_reference(reference, root, identity, errors)
        elif references:
            warnings.append(f"{identity}: references not checked; pass --root PROJECT_ROOT")
        if evidence:
            warnings.append(f"{identity}: evidence contents/results require review; file presence is not proof of success")
        if node["pm_kind"] == "gate":
            for field in ("pm_reason", "pm_resume_when", "pm_owner", "pm_basis"):
                if not node.get(field, "").strip():
                    errors.append(f"{identity}: gate requires {field}")
            if node.get("pm_stop_type") not in STOP_TYPES:
                errors.append(f"{identity}: invalid pm_stop_type")
            if node.get("pm_origin") not in ORIGINS:
                errors.append(f"{identity}: invalid pm_origin")
            if node.get("pm_origin") == "HYPOTHESIS":
                warnings.append(f"{identity}: unverified constraint; do not treat it as a proven product limitation")
            blocked = tokens(node.get("pm_blocks", ""), identity, "pm_blocks", errors)
            if not blocked or not blocked.issubset(nodes):
                errors.append(f"{identity}: pm_blocks must name existing affected nodes")
        if node["pm_kind"] == "external" and node.get("pm_effect") not in {"READ", "WRITE"}:
            errors.append(f"{identity}: external node requires pm_effect READ or WRITE")
    for edge in contract["unmanaged_edges"]:
        if edge["source"] in nodes or edge["target"] in nodes:
            errors.append(f"{edge['id']}: connected workflow arrow has no pm_kind=transition")
    for identity, edge in edges.items():
        source, target = edge["source"], edge["target"]
        if source not in nodes or target not in nodes:
            errors.append(f"{identity}: transition endpoints must reference managed nodes")
            continue
        adjacency[source].add(target)
        reverse[target].add(source)
        outgoing[source].append(edge)
        bound = edge.get("pm_max_attempts")
        if bound is None:
            unbounded[source].add(target)
        elif not re.fullmatch(r"[1-9][0-9]*", bound):
            errors.append(f"{identity}: pm_max_attempts must be a positive integer")
            unbounded[source].add(target)
        mode = edge.get("pm_mode")
        if mode not in {"data", "control"}:
            errors.append(f"{identity}: pm_mode must be data or control")
        artifact = edge.get("pm_artifact", "").strip()
        if mode == "data":
            if not TOKEN.fullmatch(artifact):
                errors.append(f"{identity}: data transition needs a single pm_artifact identifier")
            if artifact not in outputs[source]:
                errors.append(f"{identity}: {source} does not produce {artifact}")
            if artifact not in inputs[target]:
                errors.append(f"{identity}: {target} does not accept {artifact}")
            incoming[target].add(artifact)
        elif artifact:
            errors.append(f"{identity}: control transition must not declare pm_artifact")
    triggers = {identity for identity, node in nodes.items() if node["pm_kind"] == "trigger"}
    outcomes = {identity for identity, node in nodes.items() if node["pm_kind"] == "outcome"}
    if not triggers or not outcomes:
        errors.append("map requires a trigger and an outcome")
    reached = reachable(triggers, adjacency)
    terminates = reachable(outcomes, reverse)
    authorization_gates = {identity for identity, node in nodes.items() if node["pm_kind"] == "gate" and node.get("pm_stop_type") == "AUTHORIZATION"}
    unguarded = reachable(triggers, adjacency, authorization_gates)
    for identity, node in nodes.items():
        kind = node["pm_kind"]
        if identity not in reached:
            errors.append(f"{identity}: unreachable from a trigger")
        if identity not in terminates:
            errors.append(f"{identity}: no path to an outcome")
        if kind != "trigger":
            missing = inputs[identity] - incoming[identity]
            if missing:
                errors.append(f"{identity}: inputs have no producer: {', '.join(sorted(missing))}")
        if kind == "trigger" and inputs[identity]:
            errors.append(f"{identity}: express trigger context as outputs, not undeclared external inputs")
        if kind == "outcome" and outgoing[identity]:
            errors.append(f"{identity}: outcome must be terminal")
        transitions = outgoing[identity]
        if kind == "gate" or len(transitions) > 1:
            conditions = [edge.get("pm_when", "").strip() for edge in transitions]
            if len(transitions) < 2 or not all(conditions) or len(conditions) != len(set(conditions)):
                errors.append(f"{identity}: branch requires distinct explicit conditions and at least two exits")
        if kind == "gate":
            downstream = reachable({identity}, adjacency) - {identity}
            blocked = tokens(node.get("pm_blocks", ""), identity, "pm_blocks", errors)
            if blocked - downstream:
                errors.append(f"{identity}: pm_blocks must be downstream affected nodes")
        if kind == "external" and node.get("pm_effect") == "WRITE" and identity in unguarded:
            errors.append(f"{identity}: external WRITE has a route without an AUTHORIZATION gate")
    if has_cycle(unbounded):
        errors.append("unbounded cycle: mark retry transitions with pm_max_attempts and provide an exit")
    return errors, warnings


def canonical(contract: Dict[str, Any]) -> Dict[str, Any]:
    return {key: contract[key] for key in ("nodes", "edges")}


def fingerprint(contract: Dict[str, Any]) -> str:
    payload = json.dumps(canonical(contract), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {"contract_changed": fingerprint(before) != fingerprint(after)}
    for category in ("nodes", "edges"):
        old, new = before[category], after[category]
        result[category] = {
            "added": sorted(set(new) - set(old)),
            "removed": sorted(set(old) - set(new)),
            "changed": {
                identity: sorted(key for key in set(old[identity]) | set(new[identity]) if old[identity].get(key) != new[identity].get(key))
                for identity in sorted(set(old) & set(new)) if old[identity] != new[identity]
            },
        }
    return result


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "inspect", "compare"))
    parser.add_argument("file", type=Path)
    parser.add_argument("--page", help="Page ID, mandatory for multi-page maps")
    parser.add_argument("--root", type=Path, help="Project root for implementation/evidence references")
    parser.add_argument("--baseline", type=Path, help="Previous .drawio file for comparison")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as validation failure")
    args = parser.parse_args(argv)
    if args.command == "compare" and args.baseline is None:
        parser.error("compare requires --baseline FILE")
    try:
        contract = load_contract(args.file, args.page)
        errors, warnings = validate(contract, args.root)
        baseline = None
        if args.command == "compare":
            baseline = load_contract(args.baseline, args.page)
            old_errors, old_warnings = validate(baseline, args.root)
            errors.extend("baseline: " + item for item in old_errors)
            warnings.extend("baseline: " + item for item in old_warnings)
        if args.command == "validate":
            for item in errors:
                print("ERROR: " + item)
            for item in warnings:
                print("WARNING: " + item)
            print("RESULT: " + ("ERROR" if errors else "WARNING" if warnings else "PASS"))
            print("NOTE: contract structure checked; no skills, conditions or external actions were executed")
        else:
            output = compare(baseline, contract) if baseline is not None else canonical(contract)
            output.update({"contract_sha256": fingerprint(contract), "errors": errors, "warnings": warnings})
            print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if errors or (warnings and args.strict) else 0
    except (OSError, WorkflowError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
