#!/usr/bin/env python3
"""Acceptance and regression tests for Project Master 2.1."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

SKILL = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL / "scripts"
sys.path.insert(0, str(SCRIPTS))

import state  # noqa: E402
import validate_project  # noqa: E402


class ProjectMasterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="project-master-test-")
        self.root = Path(self.temporary.name) / "repo"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, script: str, *arguments: str, root: Optional[Path] = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--root", str(root or self.root), *arguments],
            text=True, capture_output=True, check=False,
        )

    def init(self, root: Optional[Path] = None, idea: str = "Сервис согласования заказов") -> Path:
        target = root or self.root
        result = self.run_cli("init_project.py", "--name", "Test Project", "--idea", idea, root=target)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return target / ".project-master"

    def make_component(self, phase: str, component: str, status: str = "READY") -> Path:
        phase_dir = self.root / ".project-master" / "phases" / f"{phase}-foundation"
        component_dir = phase_dir / "components"
        component_dir.mkdir(parents=True, exist_ok=True)
        (phase_dir / "PLAN.md").write_text("# P01: Foundation\n\nStatus: ACTIVE\n", encoding="utf-8")
        (phase_dir / "CONTEXT.md").write_text("# PHASE CONTEXT\n\nConfirmed facts only.\n", encoding="utf-8")
        local = component.split("-", 1)[1]
        path = component_dir / f"{local}-core.md"
        text = (SKILL / "assets" / "templates" / "COMPONENT.md").read_text(encoding="utf-8")
        text = text.replace("PXX-CXX", component).replace("Status: PLANNED", f"Status: {status}")
        path.write_text(text, encoding="utf-8")
        return path

    def reach_roadmap_review(self) -> None:
        state.transition(self.root, "SPECIFICATION", "Discovery complete", None)
        state.transition(self.root, "CONCEPT_REVIEW", "Specification ready", None)
        state.approve(self.root, "concept", "test owner")
        state.transition(self.root, "PROCESS_MODELING", "Concept approved", None)
        state.approve(self.root, "processes", "test owner")
        state.transition(self.root, "ARCHITECTURE", "Processes approved", None)
        state.transition(self.root, "ARCHITECTURE_REVIEW", "Architecture proposed", None)
        state.approve(self.root, "architecture", "test owner")
        state.transition(self.root, "ROADMAP", "Architecture approved", None)
        state.transition(self.root, "ROADMAP_REVIEW", "Roadmap proposed", None)

    def prepare_approved_baseline(self) -> Path:
        self.init()
        self.reach_roadmap_review()
        component = self.make_component("P01", "P01-C01")
        state.approve(self.root, "roadmap", "test owner")
        return component

    def test_01_bootstrap_starts_discovery(self) -> None:
        pm = self.init()
        data = json.loads((pm / "STATE.yaml").read_text(encoding="utf-8"))
        self.assertEqual(data["stage"], "DISCOVERY")
        self.assertIn("Сервис согласования", (pm / "VISION.md").read_text(encoding="utf-8"))

    def test_02_discovery_cannot_jump_to_execution(self) -> None:
        self.init()
        with self.assertRaises(state.StateError):
            state.transition(self.root, "EXECUTION", "forbidden jump", None)

    def test_03_roadmap_allows_exactly_one_active_component(self) -> None:
        self.init()
        self.reach_roadmap_review()
        self.make_component("P01", "P01-C01")
        self.make_component("P01", "P01-C02")
        state.set_active(self.root, "P01", "P01-C01", "Implement C01")
        state.approve(self.root, "roadmap", "test owner")
        state.transition(self.root, "EXECUTION", "Roadmap approved", None)
        with self.assertRaises(state.StateError):
            state.set_active(self.root, "P01", "P01-C02", None)

    def test_04_resume_uses_files_without_conversation(self) -> None:
        self.init()
        first = state.load_state(self.root)
        reloaded = json.loads((self.root / ".project-master" / "STATE.yaml").read_text(encoding="utf-8"))
        self.assertEqual(first, reloaded)
        self.assertIn("Test Project", state.summary(reloaded))
        self.assertIn("Next action", (self.root / ".project-master" / "CURRENT_STATE.md").read_text(encoding="utf-8"))

    def test_05_manual_bpmn_change_is_detected_without_rewrite(self) -> None:
        pm = self.init()
        bpmn = pm / "processes" / "system" / "PM-001-project-master-lifecycle.bpmn"
        sidecar = bpmn.with_suffix(".md")
        original = bpmn.read_text(encoding="utf-8")
        before = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_bpmn.py"), str(bpmn), "--no-semantic", "--check-sync", str(sidecar)],
            text=True, capture_output=True, check=False,
        )
        self.assertIn("SYNC UNCHANGED", before.stdout)
        bpmn.write_text(original + "\n", encoding="utf-8")
        after = subprocess.run(
            [sys.executable, str(SCRIPTS / "validate_bpmn.py"), str(bpmn), "--no-semantic", "--check-sync", str(sidecar)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(after.returncode, 0, after.stderr + after.stdout)
        self.assertIn("SYNC CHANGE DETECTED", after.stdout)
        self.assertEqual(bpmn.read_text(encoding="utf-8"), original + "\n")

    def test_06_change_review_preserves_resume_stage(self) -> None:
        self.init()
        state.transition(self.root, "CHANGE_REVIEW", "BPMN conflicts with approved requirement", None)
        data = state.load_state(self.root)
        self.assertEqual(data["stage"], "CHANGE_REVIEW")
        self.assertEqual(data["resume_stage"], "DISCOVERY")

    def test_07_complete_component_without_evidence_is_error(self) -> None:
        self.init()
        self.make_component("P01", "P01-C01", status="COMPLETE")
        errors, _ = validate_project.audit(self.root)
        self.assertTrue(any("COMPLETE component has no VERIFIED evidence" in item for item in errors))

    def test_08_scope_control_is_explicit(self) -> None:
        text = (SKILL / "references" / "change-control.md").read_text(encoding="utf-8")
        self.assertIn("SCOPE_CHANGE", text)
        self.assertIn("approval", text.lower())

    def test_09_three_strike_protocol_stops_repetition(self) -> None:
        text = (SKILL / "references" / "execution.md").read_text(encoding="utf-8")
        self.assertIn("Three-Strike Protocol", text)
        self.assertIn("третьей", text)
        self.assertIn("прекрати повтор", text)

    def test_10_execution_cannot_complete_directly(self) -> None:
        self.init()
        self.reach_roadmap_review()
        self.make_component("P01", "P01-C01")
        state.set_active(self.root, "P01", "P01-C01", None)
        state.approve(self.root, "roadmap", "test owner")
        state.transition(self.root, "EXECUTION", "Roadmap approved", None)
        final_review = self.root / ".project-master" / "reviews" / "final-review.md"
        final_review.write_text("# FINAL REVIEW\n\nNot complete.\n", encoding="utf-8")
        state.approve(self.root, "completion", "premature")
        with self.assertRaises(state.StateError):
            state.transition(self.root, "COMPLETE", "forbidden direct completion", None)

    def test_11_existing_agents_file_is_preserved(self) -> None:
        original = "# Existing rules\n\n- Keep this exact rule.\n"
        (self.root / "AGENTS.md").write_text(original, encoding="utf-8")
        self.init()
        result = (self.root / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(result.startswith(original.rstrip()))
        self.assertIn("Keep this exact rule", result)
        self.assertEqual(result.count("<!-- project-master:start -->"), 1)

    def test_12_repositories_never_share_state(self) -> None:
        self.init()
        second = Path(self.temporary.name) / "other-repo"
        second.mkdir()
        self.init(second, idea="Другая идея")
        first_state = state.load_state(self.root)
        second_state = state.load_state(second)
        self.assertNotEqual(first_state["project_id"], second_state["project_id"])
        self.assertNotEqual(
            (self.root / ".project-master" / "VISION.md").read_text(encoding="utf-8"),
            (second / ".project-master" / "VISION.md").read_text(encoding="utf-8"),
        )

    def test_13_bootstrap_validator_has_no_errors(self) -> None:
        self.init()
        errors, _ = validate_project.audit(self.root)
        self.assertEqual(errors, [])

    def test_14_existing_memory_is_never_overwritten(self) -> None:
        pm = self.init()
        before = (pm / "STATE.yaml").read_bytes()
        again = self.run_cli("init_project.py", "--name", "Replacement")
        self.assertNotEqual(again.returncode, 0)
        self.assertEqual((pm / "STATE.yaml").read_bytes(), before)
        plan = self.run_cli("init_project.py", "--upgrade-plan")
        self.assertEqual(plan.returncode, 0)
        self.assertIn("MIGRATION PLAN", plan.stdout)

    def test_15_verified_component_can_complete(self) -> None:
        self.init()
        self.make_component("P01", "P01-C01")
        state.set_active(self.root, "P01", "P01-C01", None)
        evidence = self.root / ".project-master" / "reviews" / "P01-C01-verification.md"
        evidence.write_text("# Evidence\n\nAll acceptance checks passed.\n", encoding="utf-8")
        state.record_verification(self.root, "VERIFIED", str(evidence.relative_to(self.root)), "unittest")
        state.complete_component(self.root)
        path = self.root / ".project-master" / "phases" / "P01-foundation" / "components" / "C01-core.md"
        self.assertEqual(state.component_status(path), "COMPLETE")
        self.assertIn("Evidence: `.project-master/reviews/P01-C01-verification.md`", path.read_text(encoding="utf-8"))

    def test_16_approval_is_bound_to_artifact_hash(self) -> None:
        pm = self.init()
        state.transition(self.root, "SPECIFICATION", "Discovery complete", None)
        state.transition(self.root, "CONCEPT_REVIEW", "Specification ready", None)
        state.approve(self.root, "concept", "test owner")
        record = state.load_state(self.root)["approval_records"]["concept"]
        self.assertRegex(record["artifact_hash"], r"^[0-9a-f]{64}$")
        self.assertTrue(record["artifacts"])
        with (pm / "VISION.md").open("a", encoding="utf-8") as handle:
            handle.write("\nChanged after approval.\n")
        with self.assertRaisesRegex(state.StateError, "requires approvals: concept"):
            state.transition(self.root, "PROCESS_MODELING", "Attempt stale gate", None)
        errors = state.approval_integrity_errors(self.root, state.load_state(self.root))
        self.assertIn("approval concept is stale: approved artifacts changed", errors)

    def test_17_event_log_tracks_state_hash(self) -> None:
        pm = self.init()
        state.set_route(
            self.root, "advisory", "economy", "mechanical", "low", "Deterministic formatting"
        )
        events = [json.loads(line) for line in (pm / "state-events.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(events[0]["type"], "project.initialized")
        self.assertEqual(events[-1]["type"], "routing.selected")
        self.assertEqual(events[-1]["state_hash"], state.state_digest(state.load_state(self.root)))
        self.assertEqual(state.validate_event_log(self.root, state.load_state(self.root)), [])

    def test_18_direct_state_edit_is_detected_by_event_log(self) -> None:
        pm = self.init()
        data = state.load_state(self.root)
        data["next_action"] = "Unjournaled edit"
        (pm / "STATE.yaml").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        errors = state.validate_event_log(self.root, data)
        self.assertTrue(any("event log/state mismatch" in item for item in errors))

    def test_19_quick_profile_requires_approved_baseline(self) -> None:
        self.init()
        with self.assertRaisesRegex(state.StateError, "approved unchanged project baseline"):
            state.set_profile(self.root, "QUICK", "Small fix", "test owner")

    def test_20_quick_profile_is_recorded_after_baseline(self) -> None:
        self.prepare_approved_baseline()
        state.set_profile(self.root, "QUICK", "Small bounded fix", "test owner")
        data = state.load_state(self.root)
        self.assertEqual(data["lifecycle_profile"], "QUICK")
        self.assertEqual(data["profile_record"]["reason"], "Small bounded fix")

    def test_21_capability_route_does_not_store_model_name(self) -> None:
        self.init()
        state.set_route(
            self.root, "advisory", "maximum", "independent_review", "high", "Critical review"
        )
        routing = state.load_state(self.root)["routing"]
        self.assertEqual(routing["required_capability"], "independent_review")
        self.assertEqual(routing["minimum_effort"], "high")
        self.assertNotIn("model", routing)

    def test_22_correction_creates_complete_change_package(self) -> None:
        self.prepare_approved_baseline()
        result = self.run_cli(
            "change.py", "--title", "Fix export", "--description", "Existing requirement is broken",
            "--kind", "CORRECTION",
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        packages = list((self.root / ".project-master" / "changes").glob("CHG-001-*"))
        self.assertEqual(len(packages), 1)
        expected = {
            "PROPOSAL.md", "REQUIREMENTS_DELTA.md", "PROCESS_DELTA.md",
            "IMPACT.md", "PLAN.md", "VERIFICATION.md",
        }
        self.assertEqual({path.name for path in packages[0].iterdir()}, expected)
        data = state.load_state(self.root)
        self.assertEqual(data["stage"], "ROADMAP_REVIEW")
        self.assertEqual(data["active_change"], "CHG-001")
        self.assertEqual(data["lifecycle_profile"], "QUICK")

    def test_23_scope_change_enters_change_review(self) -> None:
        self.prepare_approved_baseline()
        result = self.run_cli(
            "change.py", "--title", "Add approval role", "--description", "New role changes scope",
            "--kind", "SCOPE_CHANGE",
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        data = state.load_state(self.root)
        self.assertEqual(data["stage"], "CHANGE_REVIEW")
        self.assertEqual(data["resume_stage"], "ROADMAP_REVIEW")
        self.assertEqual(data["lifecycle_profile"], "STANDARD")

    def test_24_validator_rejects_incomplete_change_package(self) -> None:
        pm = self.init()
        package = pm / "changes" / "CHG-001-broken"
        package.mkdir()
        (package / "PROPOSAL.md").write_text("# broken\n", encoding="utf-8")
        errors, _ = validate_project.audit(self.root)
        self.assertTrue(any("incomplete change package CHG-001" in item for item in errors))

    def test_25_mit_license_keeps_author_attribution(self) -> None:
        license_text = (SKILL / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("MIT License", license_text)
        self.assertIn("Copyright (c) 2026 Andrey Sovetov", license_text)
        self.assertIn("shall be included", license_text)

    def test_26_event_hash_chain_detects_removed_history(self) -> None:
        pm = self.init()
        state.set_route(
            self.root, "advisory", "balanced", "balanced_reasoning", "medium", "Normal work"
        )
        log = pm / "state-events.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        log.write_text(lines[-1] + "\n", encoding="utf-8")
        errors = state.validate_event_log(self.root, state.load_state(self.root))
        self.assertTrue(any("hash chain is broken" in item for item in errors))
        with self.assertRaisesRegex(state.StateError, "refusing mutation"):
            state.set_route(
                self.root, "advisory", "economy", "mechanical", "low", "Must not append"
            )

    def test_27_explicit_migration_backs_up_and_binds_legacy_approvals(self) -> None:
        pm = self.init()
        state.approve(self.root, "concept", "legacy owner")
        legacy = state.load_state(self.root)
        legacy["schema_version"] = "2.0"
        legacy["project_master_version"] = "2.0"
        for field in ("lifecycle_profile", "profile_record", "active_change", "routing", "event_log"):
            legacy.pop(field, None)
        legacy["approval_records"]["concept"].pop("artifact_hash", None)
        legacy["approval_records"]["concept"].pop("artifacts", None)
        (pm / "STATE.yaml").write_text(json.dumps(legacy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (pm / "state-events.jsonl").unlink()
        (pm / "ROUTING.md").unlink()
        refused = self.run_cli("migrate.py", "apply")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--accept-current-approved-artifacts", refused.stderr)
        applied = self.run_cli("migrate.py", "apply", "--accept-current-approved-artifacts")
        self.assertEqual(applied.returncode, 0, applied.stderr + applied.stdout)
        migrated = state.load_state(self.root)
        self.assertEqual(migrated["schema_version"], "2.1")
        self.assertRegex(migrated["approval_records"]["concept"]["artifact_hash"], r"^[0-9a-f]{64}$")
        self.assertTrue(list((pm / "migrations").glob("2.0-to-2.1-*")))
        errors, _ = validate_project.audit(self.root)
        self.assertEqual(errors, [])

    def test_28_completion_approval_requires_final_review(self) -> None:
        self.init()
        with self.assertRaisesRegex(state.StateError, "requires reviews/final-review.md"):
            state.approve(self.root, "completion", "premature")


if __name__ == "__main__":
    unittest.main(verbosity=2)
