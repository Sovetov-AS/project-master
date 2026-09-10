#!/usr/bin/env python3
"""Validate or upsert Project Master requirement traceability rows."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

COLUMNS = ("Requirement", "Process / element", "ADR", "Component", "Verification", "Status")
REQ_RE = re.compile(r"\bREQ-(?:F|NF|BR|SEC|INT)-\d{3}\b")
PROC_RE = re.compile(r"\b(?:PROC|PM)-\d{3}\b")
ADR_RE = re.compile(r"\bADR-\d{3}\b")
COMP_RE = re.compile(r"\bP\d{2}-C\d{2}\b")


def markdown_cells(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_table(path: Path) -> Tuple[List[str], List[List[str]], int, int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        cells = markdown_cells(line) if line.lstrip().startswith("|") else []
        if tuple(cells) == COLUMNS:
            if index + 1 >= len(lines):
                raise ValueError("traceability table has no separator")
            rows: List[List[str]] = []
            cursor = index + 2
            while cursor < len(lines) and lines[cursor].lstrip().startswith("|"):
                row = markdown_cells(lines[cursor])
                if len(row) == len(COLUMNS):
                    rows.append(row)
                cursor += 1
            return lines, rows, index, cursor
    raise ValueError("traceability table header not found")


def ids_from_text(path: Path, pattern: re.Pattern[str]) -> Set[str]:
    return set(pattern.findall(path.read_text(encoding="utf-8"))) if path.is_file() else set()


def known_ids(root: Path) -> Dict[str, Set[str]]:
    pm = root / ".project-master"
    requirements = ids_from_text(pm / "REQUIREMENTS.md", REQ_RE)
    processes = {match.group(0) for path in (pm / "processes").rglob("*.bpmn") for match in [PROC_RE.search(path.name)] if match}
    adrs = {match.group(0) for path in (pm / "decisions").glob("ADR-*.md") for match in [ADR_RE.search(path.name)] if match}
    components: Set[str] = set()
    for path in (pm / "phases").glob("P*/components/C*.md"):
        phase_match = re.match(r"(P\d{2})-", path.parent.parent.name)
        component_match = re.match(r"(C\d{2})-", path.name)
        if phase_match and component_match:
            components.add(f"{phase_match.group(1)}-{component_match.group(1)}")
    return {"requirements": requirements, "processes": processes, "adrs": adrs, "components": components}


def validate(root: Path) -> Tuple[List[str], List[str]]:
    path = root / ".project-master" / "TRACEABILITY.md"
    errors: List[str] = []
    warnings: List[str] = []
    if not path.is_file():
        return ["TRACEABILITY.md is missing"], warnings
    try:
        _, rows, _, _ = parse_table(path)
    except ValueError as exc:
        return [str(exc)], warnings
    known = known_ids(root)
    seen: Set[str] = set()
    for number, row in enumerate(rows, start=1):
        requirement, process, adr, component, verification, status = row
        if requirement in seen:
            errors.append(f"duplicate traceability row: {requirement}")
        seen.add(requirement)
        if requirement not in known["requirements"]:
            errors.append(f"unknown requirement in row {number}: {requirement}")
        for ref in PROC_RE.findall(process):
            if ref not in known["processes"]:
                errors.append(f"unknown process in {requirement}: {ref}")
        for ref in ADR_RE.findall(adr):
            if ref not in known["adrs"]:
                errors.append(f"unknown ADR in {requirement}: {ref}")
        for ref in COMP_RE.findall(component):
            if ref not in known["components"]:
                errors.append(f"unknown component in {requirement}: {ref}")
        if status == "VERIFIED" and verification in {"", "—", "-"}:
            errors.append(f"{requirement} is VERIFIED without verification evidence")
    missing = known["requirements"] - seen
    for requirement in sorted(missing):
        warnings.append(f"requirement has no traceability row: {requirement}")
    return errors, warnings


def escape(value: str) -> str:
    return value.replace("|", "\\|").strip() or "—"


def upsert(root: Path, values: Sequence[str]) -> None:
    path = root / ".project-master" / "TRACEABILITY.md"
    lines, rows, start, end = parse_table(path)
    requirement = values[0]
    replaced = False
    for index, row in enumerate(rows):
        if row[0] == requirement:
            rows[index] = list(values)
            replaced = True
            break
    if not replaced:
        rows.append(list(values))
    rows.sort(key=lambda item: item[0])
    rendered = ["| " + " | ".join(escape(cell) for cell in row) + " |" for row in rows]
    new_lines = lines[: start + 2] + rendered + lines[end:]
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    set_parser = sub.add_parser("set")
    set_parser.add_argument("requirement")
    set_parser.add_argument("--process", default="—")
    set_parser.add_argument("--adr", default="—")
    set_parser.add_argument("--component", default="—")
    set_parser.add_argument("--verification", default="—")
    set_parser.add_argument("--status", required=True)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "set":
            upsert(root, (args.requirement, args.process, args.adr, args.component, args.verification, args.status))
        errors, warnings = validate(root)
        for error in errors:
            print(f"ERROR: {error}")
        for warning in warnings:
            print(f"WARNING: {warning}")
        if not errors:
            print("PASS: traceability is structurally valid")
        return 1 if errors else 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
