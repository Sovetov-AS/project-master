"""3.0 end-to-end contracts and migration/recovery regression tests."""
from __future__ import annotations
import copy
import json
import shutil
import subprocess
import threading
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))
import init_project
import state
import mission
import recover
import upgrade
import validate_project
import change
import install


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pm3-release-")
        self.root = Path(self.temp.name)
        self.definition = json.loads((SKILL / "assets/templates/MISSION-example.json").read_text())

    def tearDown(self):
        self.temp.cleanup()

    def init(self, schema="3.0", profile="STANDARD"):
        init_project.initialize(self.root, "Synthetic product", "One useful scenario", profile, False, schema)
        if schema == "3.0":
            mission.revise(self.root, self.definition, "Synthetic owner approved scenario", 1)
        return self.root / ".project-master"

    def component(self):
        directory = self.root / ".project-master/phases/P01-mvp"
        (directory / "components").mkdir(parents=True)
        (directory / "PLAN.md").write_text("# Plan\n\n| Component | Status |\n|---|---|\n| P01-C01 | READY |\n")
        (directory / "CONTEXT.md").write_text("# Relevant confirmed context\n")
        text = (SKILL / "assets/templates/COMPONENT.md").read_text().replace("PXX-CXX", "P01-C01").replace("Status: PLANNED", "Status: READY")
        path = directory / "components/C01-useful.md"
        path.write_text(text)
        return path

    def test_new_project_has_goal_not_mandatory_lifecycle_diagram(self):
        pm = self.init()
        self.assertEqual(state.load_state(self.root)["schema_version"], "3.0")
        self.assertFalse(list((pm / "processes").rglob("*.bpmn")))
        self.assertEqual(validate_project.audit(self.root), ([], []))
        self.assertEqual(recover.recover(self.root)["mission"]["goal"], self.definition["goal"])

    def test_complete_lean_increment_has_no_full_baseline_prerequisite(self):
        pm = self.init()
        self.component()
        state.transition(self.root, "SPECIFICATION", "Known scenario", None)
        state.transition(self.root, "ROADMAP", "Small increment contract", None)
        state.transition(self.root, "ROADMAP_REVIEW", "Owner sees plan", None)
        state.approve(self.root, "roadmap", "Synthetic explicit owner plan instruction")
        state.set_active(self.root, "P01", "P01-C01", "Check useful scenario")
        state.transition(self.root, "EXECUTION", "Approved plan", None)
        evidence = pm / "reviews/scenario.md"
        evidence.write_text("Synthetic test: defined acceptance checks passed.\n")
        state.record_verification(self.root, "VERIFIED", str(evidence.relative_to(self.root)), "Synthetic test")
        state.complete_component(self.root)
        state.transition(self.root, "VERIFICATION", "Increment checked", None)
        (pm / "reviews/final-review.md").write_text("# Review\nVERIFIED: synthetic scenario, no live operations\n")
        state.transition(self.root, "COMPLETION_REVIEW", "Owner review", None)
        state.approve(self.root, "completion", "Synthetic owner acceptance")
        state.transition(self.root, "COMPLETE", "Accepted", None)
        self.assertEqual(validate_project.audit(self.root), ([], []))
        state.transition(self.root, "ROADMAP", "Owner requests next increment", None)
        self.assertEqual(state.load_state(self.root)["stage"], "ROADMAP")

    def test_unknown_bootstrap_mission_cannot_be_approved_as_plan(self):
        init_project.initialize(self.root, "Synthetic", "Idea", "STANDARD", False)
        with self.assertRaisesRegex(state.StateError, "NEEDS_REVIEW"):
            state.approve(self.root, "roadmap", "Assumed owner")

    def test_layout_edit_preserves_process_approval_but_handoff_edit_does_not(self):
        pm = self.init()
        file = pm / "workflows/product.drawio"
        shutil.copyfile(SKILL / "assets/templates/WORKFLOW-plugin-example.drawio", file)
        state.approve(self.root, "processes", "Synthetic map approval")
        document = ET.parse(file)
        document.find(".//*[@id='N02']//mxGeometry").set("x", "999")
        document.write(file)
        self.assertEqual(state.approval_integrity_errors(self.root, state.load_state(self.root)), [])
        document.find(".//*[@id='E02']").set("pm_artifact", "changed.payload")
        document.write(file)
        self.assertTrue(state.approval_integrity_errors(self.root, state.load_state(self.root)))

    def test_progress_does_not_stale_plan_but_acceptance_change_does(self):
        pm = self.init()
        component = self.component()
        state.approve(self.root, "roadmap", "Synthetic owner")
        plan = component.parent.parent / "PLAN.md"
        plan.write_text(plan.read_text().replace("READY", "ACTIVE"))
        self.assertEqual(state.approval_integrity_errors(self.root, state.load_state(self.root)), [])
        component.write_text(component.read_text() + "\nAcceptance: changed contract\n")
        self.assertTrue(state.approval_integrity_errors(self.root, state.load_state(self.root)))

    def test_goal_change_invalidates_plan_but_personal_lesson_does_not(self):
        self.init()
        state.approve(self.root, "roadmap", "Synthetic owner")
        lesson = {"id": "L1", "statement": "Synthetic expert knowledge", "kind": "EXPERT_KNOWLEDGE",
                  "support": "USER_EXPERT", "status": "ADOPTED", "source": "Synthetic owner expertise",
                  "applies_to": "current scenario", "decision_source": "Synthetic owner adopts"}
        mission.learn(self.root, lesson, 2)
        self.assertEqual(state.approval_integrity_errors(self.root, state.load_state(self.root)), [])
        changed = copy.deepcopy(self.definition)
        changed["goal"] = "Different scenario"
        mission.revise(self.root, changed, "Synthetic owner revises goal", 3)
        self.assertTrue(state.approval_integrity_errors(self.root, state.load_state(self.root)))

    def test_action_stop_does_not_block_unrelated_project_work(self):
        self.init()
        state.add_blocker(self.root, "Live write lacks authority", "external.write", "Current owner grant",
                          "Synthetic current instruction", "OWNER", "No applicable grant", "owner")
        data = state.load_state(self.root)
        self.assertEqual(data["stage"], "DISCOVERY")
        self.assertEqual(data["blockers"][0]["scope"], "external.write")
        state.transition(self.root, "SPECIFICATION", "Independent local work", None)
        state.clear_blocker(self.root, 0, "Synthetic resolution: operation deferred")

    def test_stale_state_writer_cannot_overwrite_newer_memory(self):
        self.init()
        stale = state.load_state(self.root)
        state.set_route(self.root, "advisory", "economy", "mechanical", "low", "Synthetic route")
        stale["next_action"] = "Lost update"
        with self.assertRaisesRegex(state.StateError, "stale STATE"):
            state.save_state(self.root, stale)
        self.assertNotEqual(state.load_state(self.root)["next_action"], "Lost update")

    def test_unchanged_route_does_not_grow_event_log(self):
        pm = self.init()
        args = (self.root, "advisory", "economy", "mechanical", "low", "Same route")
        state.set_route(*args)
        before = (pm / "state-events.jsonl").read_bytes()
        state.set_route(*args)
        self.assertEqual((pm / "state-events.jsonl").read_bytes(), before)

    def test_pending_state_transaction_is_repaired_without_rebasing_history(self):
        pm = self.init()
        with patch.object(state, "append_event", side_effect=OSError("simulated interruption")):
            with self.assertRaises(OSError):
                state.set_route(self.root, "advisory", "economy", "mechanical", "low", "Interrupted")
        self.assertTrue((pm / "pending-state.json").is_file())
        with self.assertRaisesRegex(state.StateError, "unfinished"):
            state.set_profile(self.root, "QUICK", "Do not overwrite pending", "Synthetic")
        state.repair(self.root)
        self.assertFalse((pm / "pending-state.json").exists())
        self.assertEqual(state.validate_event_log(self.root, state.load_state(self.root)), [])
        self.assertEqual(state.load_state(self.root)["routing"]["reason"], "Interrupted")

    def test_pending_component_transaction_recovers_both_contract_and_state(self):
        pm = self.init()
        component = self.component()
        with patch.object(state, "append_event", side_effect=OSError("interrupted activation")):
            with self.assertRaises(OSError):
                state.set_active(self.root, "P01", "P01-C01", None)
        state.repair(self.root)
        self.assertEqual(state.component_status(component), "ACTIVE")
        self.assertEqual(state.load_state(self.root)["active_component"], "P01-C01")
        self.assertEqual(state.validate_event_log(self.root, state.load_state(self.root)), [])

    def test_changed_verification_evidence_cannot_complete_component(self):
        pm = self.init()
        self.component()
        state.set_active(self.root, "P01", "P01-C01", None)
        evidence = pm / "reviews/check.md"
        evidence.write_text("Passed original scenario\n")
        state.record_verification(self.root, "VERIFIED", str(evidence.relative_to(self.root)), "Synthetic")
        evidence.write_text("Changed evidence\n")
        with self.assertRaisesRegex(state.StateError, "evidence changed"):
            state.complete_component(self.root)

    def test_full_profile_can_skip_unneeded_process_modeling(self):
        self.init(profile="FULL")
        state.transition(self.root, "SPECIFICATION", "Scenario known", None)
        state.transition(self.root, "CONCEPT_REVIEW", "Review", None)
        state.approve(self.root, "concept", "Synthetic owner")
        state.transition(self.root, "ARCHITECTURE", "No business diagram needed", None)
        self.assertEqual(validate_project.audit(self.root), ([], []))

    def test_compact_change_records_existing_current_scope_authorization(self):
        self.init()
        path = change.create(self.root, "New scenario", "Scope, impact, plan", "SCOPE_CHANGE", "STANDARD",
                             "Synthetic current owner instruction: build this scenario", True)
        self.assertEqual({file.name for file in path.iterdir()}, {"PROPOSAL.md", "VERIFICATION.md", "FORMAT-3.0"})
        self.assertEqual(state.load_state(self.root)["stage"], "DISCOVERY")
        self.assertEqual(validate_project.audit(self.root), ([], []))

    def test_upgrade_preserves_history_and_owner_content_and_backs_up(self):
        pm = self.init("2.1", "FULL")
        state.approve(self.root, "concept", "Synthetic original owner")
        data = state.load_state(self.root)
        data["custom_owner_field"] = {"preserve": "private synthetic datum"}
        state.save_state(self.root, data)
        original_log = (pm / "state-events.jsonl").read_bytes()
        original_vision = (pm / "VISION.md").read_bytes()
        agents = self.root / "AGENTS.md"
        agents.write_text(agents.read_text() + "\n# Keep exact owner rules\n")
        backup = upgrade.apply(self.root, self.definition, "Synthetic explicit migration instruction")
        self.assertTrue((backup / "memory/STATE.yaml").is_file())
        self.assertEqual((pm / "VISION.md").read_bytes(), original_vision)
        self.assertTrue((pm / "state-events.jsonl").read_bytes().startswith(original_log))
        self.assertEqual(state.load_state(self.root)["custom_owner_field"], data["custom_owner_field"])
        self.assertIn("Keep exact owner rules", agents.read_text())
        self.assertEqual(state.load_state(self.root)["approval_records"]["concept"]["source"], "Synthetic original owner")
        self.assertEqual(validate_project.audit(self.root), ([], []))
        before = (pm / "STATE.yaml").read_bytes()
        result = recover.recover(self.root)
        self.assertEqual(result["mission"]["goal"], self.definition["goal"])
        self.assertEqual(result["errors"], [])
        self.assertEqual((pm / "STATE.yaml").read_bytes(), before)

    def test_upgrade_refuses_stale_approval_and_existing_personal_mission(self):
        pm = self.init("2.1", "FULL")
        state.approve(self.root, "concept", "Synthetic owner")
        vision = pm / "VISION.md"
        vision.write_text(vision.read_text() + "\nUnapproved change\n")
        with self.assertRaisesRegex(state.StateError, "pre-existing drift"):
            upgrade.apply(self.root, self.definition, "Synthetic upgrade instruction")
        self.assertFalse((pm / "private/MISSION.json").exists())

    def test_completion_checks_current_evidence_not_only_old_verified_flag(self):
        pm = self.init()
        evidence = pm / "reviews/end.md"
        evidence.write_text("Synthetic acceptance evidence\n")
        state.record_verification(self.root, "VERIFIED", str(evidence.relative_to(self.root)), "Synthetic")
        data = state.load_state(self.root)
        data["stage"] = "COMPLETION_REVIEW"
        state.save_state(self.root, data, "synthetic.review")
        (pm / "reviews/final-review.md").write_text("# Final synthetic review\n")
        state.approve(self.root, "completion", "Synthetic owner")
        evidence.unlink()
        with self.assertRaisesRegex(state.StateError, "evidence changed or missing"):
            state.transition(self.root, "COMPLETE", "Do not trust deleted evidence", None)

    def test_parallel_thread_cannot_reenter_other_threads_memory_lock(self):
        self.init()
        failures = []
        def writer():
            try:
                state.set_profile(self.root, "QUICK", "Other writer", "Synthetic")
            except state.StateError as exc:
                failures.append(str(exc))
        with state.exclusive(self.root):
            worker = threading.Thread(target=writer)
            worker.start()
            worker.join(timeout=5)
        self.assertTrue(any("writer active" in error for error in failures))

    def test_installer_preserves_unknown_custom_files_and_backs_up_prior_skill(self):
        source = self.root / "source"
        source.mkdir()
        (source / "SKILL.md").write_text("---\nname: project-master\nmetadata:\n  version: '3.0'\n---\nSynthetic\n")
        (source / "LICENSE").write_text("Synthetic license fixture\n")
        subprocess.run(["git", "init", "-q"], cwd=source, check=True)
        subprocess.run(["git", "add", "SKILL.md", "LICENSE"], cwd=source, check=True)
        subprocess.run(["git", "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid", "commit", "-qm", "Synthetic release"], cwd=source, check=True)
        target = self.root / "skills/project-master"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("name: project-master\nold synthetic skill\n")
        (target / "custom.txt").write_text("keep user customization\n")
        backup = install.install(source, target, self.root / "backups", True)
        self.assertEqual((target / "SKILL.md").read_bytes(), (source / "SKILL.md").read_bytes())
        self.assertIn("old synthetic", (backup / "skill/SKILL.md").read_text())
        self.assertEqual((target / "custom.txt").read_text(), "keep user customization\n")
        self.assertFalse((target / ".git").exists())
        (source / "untracked.txt").write_text("Not included accidentally\n")
        with self.assertRaisesRegex(ValueError, "untracked files"):
            install.install(source, target, self.root / "backups", True)


if __name__ == "__main__":
    unittest.main()
