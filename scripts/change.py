#!/usr/bin/env python3
"""Create an auditable Project Master change package."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import state as pm_state

TEMPLATES = {
    "PROPOSAL.md": "CHANGE_PROPOSAL.md",
    "REQUIREMENTS_DELTA.md": "CHANGE_REQUIREMENTS_DELTA.md",
    "PROCESS_DELTA.md": "CHANGE_PROCESS_DELTA.md",
    "IMPACT.md": "CHANGE_IMPACT.md",
    "PLAN.md": "CHANGE_PLAN.md",
    "VERIFICATION.md": "CHANGE_VERIFICATION.md",
}


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:48] or "change"


def next_change_id(changes: Path) -> str:
    numbers = []
    for path in changes.glob("CHG-*"):
        match = re.match(r"CHG-(\d{3})", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return f"CHG-{max(numbers, default=0) + 1:03d}"


def render(text: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def ensure_profile_allowed(root: Path, data: Dict[str, object], profile: str) -> None:
    if profile not in pm_state.LIFECYCLE_PROFILES:
        raise pm_state.StateError(f"unknown lifecycle profile: {profile}")
    if profile not in {"QUICK", "STANDARD"}:
        return
    baseline = ("concept", "architecture", "roadmap")
    missing = [area for area in baseline if not data.get("approvals", {}).get(area)]  # type: ignore[union-attr]
    stale = pm_state.approval_integrity_errors(root, data, baseline)
    if missing or stale:
        raise pm_state.StateError(
            f"{profile} requires an approved unchanged baseline: {'; '.join(missing + stale)}"
        )


def create(root: Path, title: str, description: str, kind: str, profile: Optional[str], source: str) -> Path:
    root = root.resolve()
    data = pm_state.load_state(root)
    pm_state.ensure_event_log_current(root, data)
    if data.get("stage") in pm_state.SIDE_STAGES:
        raise pm_state.StateError(f"resolve current side stage before creating a change: {data.get('stage')}")
    selected_profile = profile or ("QUICK" if kind == "CORRECTION" else "STANDARD")
    ensure_profile_allowed(root, data, selected_profile)
    changes = pm_state.project_dir(root) / "changes"
    changes.mkdir(parents=True, exist_ok=True)
    change_id = next_change_id(changes)
    target = changes / f"{change_id}-{safe_slug(title)}"
    templates = Path(__file__).resolve().parent.parent / "assets" / "templates"
    missing = [name for name in TEMPLATES.values() if not (templates / name).is_file()]
    if missing:
        raise pm_state.StateError(f"change templates missing: {', '.join(missing)}")
    values = {
        "CHANGE_ID": change_id,
        "CHANGE_TITLE": title.strip(),
        "CHANGE_DESCRIPTION": description.strip(),
        "CHANGE_KIND": kind,
        "CHANGE_PROFILE": selected_profile,
        "CREATED_AT": pm_state.now(),
    }
    temporary = Path(tempfile.mkdtemp(prefix=f".{change_id}-", dir=str(changes)))
    try:
        for output, template in TEMPLATES.items():
            text = render((templates / template).read_text(encoding="utf-8"), values)
            pm_state.atomic_write(temporary / output, text)
        os.replace(str(temporary), str(target))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    data = pm_state.load_state(root)
    old_profile = data.get("lifecycle_profile")
    data["lifecycle_profile"] = selected_profile
    data["profile_record"] = {
        "profile": selected_profile, "at": pm_state.now(), "source": source,
        "reason": f"{kind} {change_id}",
    }
    data["active_change"] = change_id
    data["next_action"] = (
        f"Review and approve {change_id} before changing approved sources of truth."
        if kind == "SCOPE_CHANGE" else f"Implement {change_id} within the unchanged approved baseline."
    )
    pm_state.save_state(root, data, "change.created", {
        "change_id": change_id, "kind": kind, "profile": selected_profile,
        "path": target.relative_to(pm_state.project_dir(root)).as_posix(),
        "profile_before": old_profile, "source": source,
    })
    if kind == "SCOPE_CHANGE":
        pm_state.transition(root, "CHANGE_REVIEW", f"{change_id} requires scope approval", data["next_action"])
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--kind", choices=("CORRECTION", "SCOPE_CHANGE"), required=True)
    parser.add_argument("--profile", choices=pm_state.LIFECYCLE_PROFILES)
    parser.add_argument("--source", default="user request")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        target = create(args.root, args.title, args.description, args.kind, args.profile, args.source)
        print(f"PASS: created {target}")
        return 0
    except (OSError, pm_state.StateError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
