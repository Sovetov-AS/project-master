#!/usr/bin/env python3
"""Durable Project Master 3.0 goal/strategy, measured outcomes and personal lessons.

One atomic JSON store preserves definition revisions and observations. This module
does not schedule agents, authorize external actions, or replace legacy STATE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = "3.0"
MAX_BYTES = 16 * 1024 * 1024


class MissionError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("timezone required")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise MissionError(f"invalid timezone-aware timestamp: {value}") from exc


def digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def goal_digest(definition: Dict[str, Any]) -> str:
    return digest({key: definition[key] for key in ("goal_id", "goal", "mode", "success_criteria")})


def read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise MissionError("memory exceeds 16 MiB; archive with an explicit migration, never truncate history")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise MissionError("expected JSON object")
        return value
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise MissionError(f"invalid JSON: {exc}") from exc


def number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def required_text(data: Dict[str, Any], field: str) -> None:
    if not isinstance(data.get(field), str) or not data[field].strip():
        raise MissionError(f"{field} requires non-empty text")


def validate_definition(definition: Dict[str, Any]) -> None:
    for field in ("goal_id", "goal", "long_term_direction"):
        required_text(definition, field)
    if definition.get("mode") not in {"BUILD", "OPERATE"}:
        raise MissionError("mode must be BUILD or OPERATE")
    criteria = definition.get("success_criteria")
    if not isinstance(criteria, list) or not criteria or any(not isinstance(item, str) or not item.strip() for item in criteria):
        raise MissionError("success_criteria requires explicit acceptance criteria")
    stages = definition.get("increments")
    if not isinstance(stages, list) or not stages or any(not isinstance(stage, dict) for stage in stages):
        raise MissionError("increments requires a non-empty list of product increments")
    ids = []
    for stage in stages:
        for field in ("id", "outcome", "check", "extension_seam", "not_now"):
            required_text(stage, field)
        ids.append(stage["id"])
    if len(ids) != len(set(ids)) or definition.get("current_increment") not in ids:
        raise MissionError("increment IDs must be unique and current_increment must reference one")
    metrics = definition.get("metrics", [])
    if not isinstance(metrics, list) or any(not isinstance(metric, dict) for metric in metrics):
        raise MissionError("metrics must be a list of metric definitions")
    if definition["mode"] == "OPERATE" and not metrics:
        raise MissionError("OPERATE requires at least one measurable outcome metric")
    metric_ids = []
    for metric in metrics:
        for field in ("id", "name", "unit", "window", "source"):
            required_text(metric, field)
        if metric.get("operator") not in {"gte", "lte", "eq"} or not number(metric.get("target")):
            raise MissionError("metric requires operator gte/lte/eq and a finite numeric target")
        if not number(metric.get("max_age_hours")) or metric["max_age_hours"] <= 0:
            raise MissionError("metric requires positive max_age_hours")
        metric_ids.append(metric["id"])
    if len(metric_ids) != len(set(metric_ids)):
        raise MissionError("metric IDs must be unique")
    references = definition.get("memory_refs", [])
    if not isinstance(references, list) or any(not isinstance(reference, dict) for reference in references):
        raise MissionError("memory_refs must be a list")
    for reference in references:
        required_text(reference, "path")
        required_text(reference, "purpose")


def store_path(root: Path) -> Path:
    pm = root.resolve() / ".project-master"
    if not pm.is_dir():
        raise MissionError("project memory directory is missing; initialize the project first")
    if pm.is_symlink():
        raise MissionError("project memory directory must not be a symlink")
    private = pm / "private"
    if not private.is_dir() or private.is_symlink():
        raise MissionError("private project memory directory is missing or is a symlink")
    return private / "MISSION.json"


def load(root: Path) -> Dict[str, Any]:
    path = store_path(root)
    if path.is_symlink():
        raise MissionError("MISSION.json must not be a symlink")
    data = read_json(path)
    if data.get("schema_version") != SCHEMA:
        raise MissionError("unsupported mission schema")
    if not isinstance(data.get("revision"), int) or data["revision"] < 1:
        raise MissionError("invalid memory revision")
    checksum = data.pop("sha256", None)
    if checksum != digest(data):
        raise MissionError("memory integrity mismatch; restore/reconcile a saved copy, do not silently rebaseline")
    data["sha256"] = checksum
    history = data.get("definition_history")
    if not isinstance(history, list) or not history:
        raise MissionError("definition history is missing")
    validate_definition(history[-1]["definition"])
    return data


@contextmanager
def exclusive(root: Path):
    lock = store_path(root).with_suffix(".lock")
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise MissionError("memory writer is active or left a stale MISSION.lock; do not overwrite") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def save(root: Path, data: Dict[str, Any]) -> None:
    data = dict(data)
    data.pop("sha256", None)
    data["sha256"] = digest(data)
    raw = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    if len(raw) > MAX_BYTES:
        raise MissionError("memory exceeds 16 MiB; no history was removed")
    path = store_path(root)
    descriptor, temporary = tempfile.mkstemp(prefix=".mission-", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize(root: Path, definition: Dict[str, Any], source: str) -> None:
    validate_definition(definition)
    required_text({"source": source}, "source")
    pm = root.resolve() / ".project-master"
    if not pm.is_dir() or pm.is_symlink():
        raise MissionError("initialize project memory first; symlinks are not supported")
    private = pm / "private"
    if private.is_symlink():
        raise MissionError("private memory must not be a symlink")
    private.mkdir(exist_ok=True, mode=0o700)
    ignore = private / ".gitignore"
    expected_ignore = "*\n!.gitignore\n"
    if ignore.is_symlink():
        raise MissionError("private .gitignore must not be a symlink")
    if ignore.exists():
        if ignore.read_text(encoding="utf-8") != expected_ignore:
            raise MissionError("existing private .gitignore differs; inspect privacy rules instead of overwriting")
    else:
        with ignore.open("x", encoding="utf-8") as handle:
            handle.write(expected_ignore)
    with exclusive(root):
        if store_path(root).exists():
            raise MissionError("refusing to overwrite existing mission; use revise with expected revision")
        save(root, {"schema_version": SCHEMA, "revision": 1, "definition_history": [
            {"recorded_at": utc_now(), "source": source, "definition": definition}
        ], "observations": [], "lessons": []})


def revise(root: Path, definition: Dict[str, Any], source: str, expected_revision: int) -> None:
    validate_definition(definition)
    required_text({"source": source}, "source")
    with exclusive(root):
        data = load(root)
        if data["revision"] != expected_revision:
            raise MissionError("stale revision: reload memory before changing the goal or strategy")
        if data["definition_history"][-1]["definition"] == definition:
            return
        data["definition_history"].append({"recorded_at": utc_now(), "source": source, "definition": definition})
        data["revision"] += 1
        save(root, data)


def evidence_path(root: Path, relative: str) -> Path:
    path = (root.resolve() / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(root.resolve()):
        raise MissionError("evidence must be a project-relative file inside the project root")
    if not path.is_file():
        raise MissionError(f"evidence file is missing: {relative}")
    return path


def record(root: Path, observation: Dict[str, Any], expected_revision: int) -> None:
    for field in ("id", "metric_id", "source", "period_start", "period_end", "observed_at"):
        required_text(observation, field)
    if not number(observation.get("value")):
        raise MissionError("observation value must be finite and numeric; absence is not zero")
    if observation.get("status") not in {"VERIFIED", "UNVERIFIED"}:
        raise MissionError("observation status must be VERIFIED or UNVERIFIED")
    start, end, observed = (timestamp(observation[key]) for key in ("period_start", "period_end", "observed_at"))
    if not start <= end <= observed <= timestamp(utc_now()):
        raise MissionError("observation requires period_start <= period_end <= observed_at <= now")
    with exclusive(root):
        data = load(root)
        if data["revision"] != expected_revision:
            raise MissionError("stale revision: reload memory before recording the observation")
        definition = data["definition_history"][-1]["definition"]
        metrics = {metric["id"]: metric for metric in definition.get("metrics", [])}
        if observation["metric_id"] not in metrics:
            raise MissionError("observation references unknown metric")
        if any(item["id"] == observation["id"] for item in data["observations"]):
            raise MissionError("observation ID already exists; history cannot be overwritten")
        observation = dict(observation)
        observation["metric_sha256"] = digest(metrics[observation["metric_id"]])
        observation["goal_id"] = definition["goal_id"]
        observation["goal_sha256"] = goal_digest(definition)
        evidence = observation.get("evidence")
        if observation["status"] == "VERIFIED" and not isinstance(evidence, str):
            raise MissionError("VERIFIED requires an evidence reference; validator cannot confirm its meaning")
        if evidence:
            observation["evidence_sha256"] = hashlib.sha256(evidence_path(root, evidence).read_bytes()).hexdigest()
        elif observation["status"] == "VERIFIED":
            raise MissionError("VERIFIED requires a non-empty evidence reference")
        data["observations"].append(observation)
        data["revision"] += 1
        save(root, data)


def learn(root: Path, lesson: Dict[str, Any], expected_revision: int) -> None:
    """Save a scoped lesson, never execute it or modify the global skill."""
    for field in ("id", "statement", "source", "applies_to"):
        required_text(lesson, field)
    if lesson.get("kind") not in {"EXPERT_KNOWLEDGE", "USER_PREFERENCE", "PROCESS_LESSON", "HYPOTHESIS"}:
        raise MissionError("invalid lesson kind")
    if lesson.get("support") not in {"USER_EXPERT", "USER_FEEDBACK", "OBSERVED_RESULT", "AGENT_HYPOTHESIS"}:
        raise MissionError("invalid lesson support")
    if lesson.get("status") not in {"PROPOSED", "ADOPTED", "RETIRED"}:
        raise MissionError("lesson status must be PROPOSED, ADOPTED or RETIRED")
    if lesson["status"] in {"ADOPTED", "RETIRED"}:
        required_text(lesson, "decision_source")
        if lesson["support"] == "AGENT_HYPOTHESIS":
            raise MissionError("agent hypothesis cannot adopt or retire a rule without feedback/evidence")
    if lesson["support"] == "OBSERVED_RESULT":
        required_text(lesson, "evidence")
    with exclusive(root):
        data = load(root)
        if data["revision"] != expected_revision:
            raise MissionError("stale revision: reload memory before saving a lesson")
        lessons = data.get("lessons", [])
        ids = {item["id"] for item in lessons}
        if lesson["id"] in ids:
            raise MissionError("lesson ID already exists; record a new lesson with supersedes instead")
        if lesson.get("supersedes") and lesson["supersedes"] not in ids:
            raise MissionError("supersedes references unknown lesson")
        lesson = dict(lesson)
        lesson["recorded_at"] = utc_now()
        lesson["goal_id"] = data["definition_history"][-1]["definition"]["goal_id"]
        if lesson.get("evidence"):
            lesson["evidence_sha256"] = hashlib.sha256(evidence_path(root, lesson["evidence"]).read_bytes()).hexdigest()
        data.setdefault("lessons", []).append(lesson)
        data["revision"] += 1
        save(root, data)


def snapshot(root: Path, as_of: Optional[str] = None) -> Dict[str, Any]:
    data = load(root)
    definition = data["definition_history"][-1]["definition"]
    now = timestamp(as_of or utc_now())
    metrics = []
    for metric in definition.get("metrics", []):
        observations = [item for item in data["observations"] if item["metric_id"] == metric["id"] and item["goal_sha256"] == goal_digest(definition) and item["metric_sha256"] == digest(metric) and timestamp(item["observed_at"]) <= now]
        current = max(enumerate(observations), key=lambda pair: (timestamp(pair[1]["period_end"]), timestamp(pair[1]["observed_at"]), pair[0]))[1] if observations else None
        status, met = "NO_DATA", None
        if current:
            status = current["status"]
            if status == "VERIFIED":
                try:
                    evidence = evidence_path(root, current["evidence"])
                    if hashlib.sha256(evidence.read_bytes()).hexdigest() != current["evidence_sha256"]:
                        status = "EVIDENCE_CHANGED"
                except (OSError, MissionError):
                    status = "EVIDENCE_MISSING"
                if status == "VERIFIED" and (now - timestamp(current["period_end"])).total_seconds() > metric["max_age_hours"] * 3600:
                    status = "STALE"
                if status == "VERIFIED":
                    value, target = current["value"], metric["target"]
                    met = value >= target if metric["operator"] == "gte" else value <= target if metric["operator"] == "lte" else value == target
            metrics.append({"id": metric["id"], "name": metric["name"], "target": metric["target"], "operator": metric["operator"], "unit": metric["unit"], "window": metric["window"], "value": current["value"], "period_start": current["period_start"], "period_end": current["period_end"], "status": status, "target_met": met, "evidence": current.get("evidence")})
        else:
            metrics.append({"id": metric["id"], "name": metric["name"], "target": metric["target"], "operator": metric["operator"], "unit": metric["unit"], "window": metric["window"], "value": None, "status": status, "target_met": None})
    increment = next(item for item in definition["increments"] if item["id"] == definition["current_increment"])
    references = definition.get("memory_refs", [])
    lessons = data.get("lessons", [])
    superseded = {item["supersedes"] for item in lessons if item.get("supersedes") and item["status"] in {"ADOPTED", "RETIRED"}}
    current_lessons = []
    for lesson in lessons:
        if lesson["id"] in superseded or lesson["status"] == "RETIRED" or lesson["goal_id"] != definition["goal_id"]:
            continue
        recovered = dict(lesson)
        if lesson.get("evidence"):
            try:
                evidence = evidence_path(root, lesson["evidence"])
                recovered["evidence_status"] = "PRESENT_UNCHANGED" if hashlib.sha256(evidence.read_bytes()).hexdigest() == lesson["evidence_sha256"] else "CHANGED"
            except (OSError, MissionError):
                recovered["evidence_status"] = "MISSING"
        current_lessons.append(recovered)
    adopted = [item for item in current_lessons if item["status"] == "ADOPTED"]
    proposed = [item for item in current_lessons if item["status"] == "PROPOSED"]
    return {
        "revision": data["revision"], "goal_id": definition["goal_id"], "goal": definition["goal"], "mode": definition["mode"],
        "long_term_direction": definition["long_term_direction"], "success_criteria": definition["success_criteria"],
        "current_increment": increment, "metrics": metrics[:10], "additional_metrics": max(0, len(metrics) - 10),
        "memory_refs": references[:5], "additional_references": max(0, len(references) - 5),
        "history_count": len(data["definition_history"]), "observation_count": len(data["observations"]),
        "adopted_lessons": adopted[-5:], "additional_adopted_lessons": max(0, len(adopted) - 5),
        "proposed_lessons": proposed[-3:], "additional_proposed_lessons": max(0, len(proposed) - 3),
        "note": "Goal/strategy recovered from files. Metric comparisons are not project acceptance or authority for external actions. Evidence semantics and measurement-window compatibility still require review.",
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "revise", "record", "learn"):
        command = subparsers.add_parser(name)
        command.add_argument("--file", type=Path, required=True, help="Private input: definition for init/revise, observation for record, lesson for learn")
        if name in {"init", "revise"}:
            command.add_argument("--source", required=True, help="Actual owner's instruction/decision; not a grant of new authority")
        if name != "init":
            command.add_argument("--expected-revision", type=int, required=True)
    show = subparsers.add_parser("show")
    show.add_argument("--full", action="store_true", help="Read full history rather than the compact recovery snapshot")
    args = parser.parse_args(argv)
    try:
        if args.command == "show":
            print(json.dumps(load(args.root) if args.full else snapshot(args.root), ensure_ascii=False, indent=2))
        elif args.command == "init":
            initialize(args.root, read_json(args.file), args.source)
        elif args.command == "revise":
            revise(args.root, read_json(args.file), args.source, args.expected_revision)
        elif args.command == "record":
            record(args.root, read_json(args.file), args.expected_revision)
        else:
            learn(args.root, read_json(args.file), args.expected_revision)
        return 0
    except (OSError, MissionError, KeyError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
