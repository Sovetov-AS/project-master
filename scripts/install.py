#!/usr/bin/env python3
"""Backed-up USER skill update from an explicit release checkout; no project migration."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
import state


def install(source: Path, target: Path, backup_root: Path, apply=False):
    source, target, backup_root = source.resolve(), target.absolute(), backup_root.resolve()
    if target.name != "project-master" or target.is_symlink() or source == target.resolve():
        raise ValueError("expected distinct, non-symlink project-master target directory")
    if not source.joinpath(".git").exists():
        raise ValueError("install requires an explicit Git release checkout")
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=source, capture_output=True, text=True, check=True)
    if dirty.stdout.strip():
        raise ValueError("source checkout is dirty or has untracked files; commit the complete release before installation")
    result = subprocess.run(["git", "ls-files", "-z"], cwd=source, capture_output=True, check=True)
    files = [Path(item) for item in result.stdout.decode().split("\0") if item]
    if not files or any(part in {".project-master", "private", ".env", "STATE.lock", "MISSION.json"} for file in files for part in file.parts):
        raise ValueError("public package contains prohibited owner-memory paths")
    for file in files:
        if (source / file).is_symlink() or not (source / file).resolve().is_relative_to(source):
            raise ValueError("source symlinks/path escape require review")
        if any(parent.is_symlink() for parent in (target / file).parents if parent == target or target in parent.parents) or (target / file).is_symlink():
            raise ValueError("target contains symlinks; refusing implicit external writes")
    if "name: project-master" not in (source / "SKILL.md").read_text(encoding="utf-8"):
        raise ValueError("source skill identity mismatch")
    if target.exists() and (not target.is_dir() or not (target / "SKILL.md").is_file() or "name: project-master" not in (target / "SKILL.md").read_text(encoding="utf-8")):
        raise ValueError("existing target is not the expected skill")
    if backup_root.is_relative_to(target.resolve()) or backup_root.is_relative_to(source) or target.resolve().is_relative_to(source):
        raise ValueError("backup must be outside source and installed skill")
    if not apply:
        print(f"PLAN: {len(files)} public files -> {target}; full existing skill backup -> {backup_root}")
        return None
    backup = backup_root / ("before-3.0-" + state.now().replace(":", "") + "-" + uuid.uuid4().hex[:8])
    backup.mkdir(parents=True, mode=0o700)
    if target.exists():
        shutil.copytree(target, backup / "skill")
    target.mkdir(parents=True, exist_ok=True)
    manifest = {}
    # Preserve unknown owner customization files; never recursively remove the target.
    for file in files:
        destination = target / file
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / file, destination)
        wanted = hashlib.sha256((source / file).read_bytes()).hexdigest()
        if hashlib.sha256(destination.read_bytes()).hexdigest() != wanted:
            raise ValueError(f"installed file mismatch: {file}")
        manifest[file.as_posix()] = wanted
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source, capture_output=True, text=True, check=True).stdout.strip()
    state.atomic_write(target / ".installation.json", json.dumps({"release": "3.0.0", "commit": commit, "files": manifest}, indent=2) + "\n")
    print(f"PASS: installed {len(files)} verified files; previous skill backup: {backup}")
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        install(args.source, args.target, args.backup_root, args.apply)
        return 0
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
