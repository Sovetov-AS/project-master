"""Read project-owned outcome references without changing the plan or its status."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def project_file(directory: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("expected a relative project-memory path")
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()):
        raise ValueError("path leaves project memory")
    return path


def read_object(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def read_link(directory: Path, item: dict) -> dict:
    path = project_file(directory, item["path"])
    if not isinstance(item["label"], str):
        raise ValueError("invalid link label")
    result = {"label": item["label"], "path": ".project-master/" + item["path"]}
    digest = item.get("sha256")
    if not path.is_file():
        result["status"] = "missing"
    elif digest is None:
        result["status"] = "present"
    else:
        with path.open("rb") as stream:
            checksum = hashlib.sha256()
            for chunk in iter(lambda: stream.read(65536), b""):
                checksum.update(chunk)
        result["status"] = "matches_snapshot" if checksum.hexdigest() == digest else "changed"
    return result


def load(root: Path) -> dict | None:
    directory = root / ".project-master"
    config_path = project_file(directory, "plan-context.json")
    if not config_path.exists():
        return None
    config = read_object(config_path)
    source = config["source"]
    pending = config.get("pending")
    if pending is not None and project_file(directory, pending).exists():
        raise ValueError("plan update pending; recover it with the plan editor")
    plan = read_object(project_file(directory, source))
    if type(plan["revision"]) is not int or plan["revision"] < 0:
        raise ValueError("invalid saved plan revision")
    steps = {}
    for row in plan["steps"]:
        identifier = row["id"]
        if not isinstance(identifier, str) or not identifier or identifier in steps:
            raise ValueError("invalid or duplicate outcome ID")
        steps[identifier] = row

    def outcome(identifier: str) -> dict:
        row = steps[identifier]
        if not all(isinstance(row[key], str) and row[key].strip() for key in ("title", "body")):
            raise ValueError("outcome and acceptance criterion are required")
        if type(row["done"]) is not bool:
            raise ValueError("invalid checklist mark")
        return {
            "id": identifier,
            "outcome": row["title"],
            "acceptance_criterion": row["body"],
            "checklist_marked": row["done"],
            "links": [read_link(directory, link) for link in row.get("links", [])],
        }

    result = {
        "source": ".project-master/" + source,
        "revision": plan["revision"],
        "goal": outcome(config["goal"]),
        "current": outcome(config["current"]),
    }
    if pending is not None and project_file(directory, pending).exists():
        raise ValueError("plan update pending; recover it with the plan editor")
    return result
