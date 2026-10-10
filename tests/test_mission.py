#!/usr/bin/env python3
"""Durable goal/measurement/learning behavior, privacy, CAS and recovery tests."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))

import mission  # noqa: E402


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="project-master-mission-")
        self.root = Path(self.temporary.name).resolve()
        (self.root / ".project-master").mkdir()
        self.definition = json.loads((SKILL / "assets/templates/MISSION-example.json").read_text(encoding="utf-8"))
        self.definition["mode"] = "OPERATE"
        self.definition["metrics"] = [{
            "id": "MET-001", "name": "Подтверждённые полезные результаты", "unit": "results",
            "operator": "gte", "target": 3, "window": "последний проверенный цикл",
            "source": "проверенный отчёт цикла", "max_age_hours": 48,
        }]
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.evidence = self.root / "evidence.json"
        self.evidence.write_text('{"confirmed": 3}', encoding="utf-8")
        self.observation = {
            "id": "OBS-001", "metric_id": "MET-001", "value": 3, "status": "VERIFIED",
            "source": "test fixture", "period_start": (self.now - timedelta(hours=2)).isoformat(),
            "period_end": (self.now - timedelta(hours=1)).isoformat(),
            "observed_at": self.now.isoformat(), "evidence": "evidence.json",
        }
        self.lesson = {
            "id": "LESSON-001", "statement": "Различать подтверждённый результат и выполненный вызов",
            "kind": "EXPERT_KNOWLEDGE", "support": "USER_EXPERT", "source": "test owner explanation",
            "applies_to": "verification of this project", "status": "ADOPTED", "decision_source": "test owner request",
        }

    def tearDown(self):
        self.temporary.cleanup()

    def init(self):
        mission.initialize(self.root, self.definition, "test owner instruction")

    def test_recovery_keeps_goal_strategy_and_history_without_chat(self):
        self.init()
        recovered = mission.snapshot(self.root)
        self.assertEqual(recovered["goal"], self.definition["goal"])
        self.assertEqual(recovered["long_term_direction"], self.definition["long_term_direction"])
        self.assertEqual(recovered["current_increment"]["id"], "INC-001")
        self.assertEqual(recovered["metrics"][0]["status"], "NO_DATA")
        self.assertIsNone(recovered["metrics"][0]["value"])

    def test_operating_mode_needs_outcome_metric_but_build_mode_does_not(self):
        self.definition["metrics"] = []
        with self.assertRaises(mission.MissionError):
            self.init()
        self.definition["mode"] = "BUILD"
        self.init()
        self.assertEqual(mission.snapshot(self.root)["mode"], "BUILD")

    def test_init_does_not_overwrite_owner_memory(self):
        self.init()
        before = mission.store_path(self.root).read_bytes()
        with self.assertRaises(mission.MissionError):
            self.init()
        self.assertEqual(mission.store_path(self.root).read_bytes(), before)

    def test_measured_result_is_not_project_completion(self):
        self.init()
        mission.record(self.root, self.observation, 1)
        snapshot = mission.snapshot(self.root)
        self.assertTrue(snapshot["metrics"][0]["target_met"])
        self.assertNotIn("complete", snapshot)
        self.assertNotIn("achieved", snapshot)
        self.assertEqual(snapshot["goal"], self.definition["goal"])

    def test_unknown_unverified_and_expired_results_are_not_success(self):
        self.init()
        self.observation["status"] = "UNVERIFIED"
        mission.record(self.root, self.observation, 1)
        self.assertIsNone(mission.snapshot(self.root)["metrics"][0]["target_met"])
        self.observation["id"] = "OBS-002"
        self.observation["status"] = "VERIFIED"
        mission.record(self.root, self.observation, 2)
        stale = mission.snapshot(self.root, (self.now + timedelta(days=4)).isoformat())
        self.assertEqual(stale["metrics"][0]["status"], "STALE")
        self.assertIsNone(stale["metrics"][0]["target_met"])

    def test_rereading_old_period_does_not_make_it_fresh(self):
        self.init()
        self.observation["period_start"] = (self.now - timedelta(days=9)).isoformat()
        self.observation["period_end"] = (self.now - timedelta(days=8)).isoformat()
        mission.record(self.root, self.observation, 1)
        self.assertEqual(mission.snapshot(self.root)["metrics"][0]["status"], "STALE")

    def test_evidence_edit_or_deletion_invalidates_measurement(self):
        self.init()
        mission.record(self.root, self.observation, 1)
        self.evidence.write_text('{"confirmed": 0}', encoding="utf-8")
        self.assertEqual(mission.snapshot(self.root)["metrics"][0]["status"], "EVIDENCE_CHANGED")
        self.assertIsNone(mission.snapshot(self.root)["metrics"][0]["target_met"])
        self.evidence.unlink()
        self.assertEqual(mission.snapshot(self.root)["metrics"][0]["status"], "EVIDENCE_MISSING")

    def test_revise_preserves_old_goal_and_does_not_reuse_old_success(self):
        self.init()
        mission.record(self.root, self.observation, 1)
        revised = copy.deepcopy(self.definition)
        revised["goal"] = "Новая цель, явно выбранная владельцем"
        mission.revise(self.root, revised, "test owner changed goal", 2)
        data = mission.load(self.root)
        self.assertEqual(data["definition_history"][0]["definition"]["goal"], self.definition["goal"])
        self.assertEqual(len(data["observations"]), 1)
        self.assertEqual(mission.snapshot(self.root)["metrics"][0]["status"], "NO_DATA")

    def test_metric_definition_change_does_not_reuse_incompatible_observation(self):
        self.init()
        mission.record(self.root, self.observation, 1)
        revised = copy.deepcopy(self.definition)
        revised["metrics"][0]["unit"] = "different population"
        mission.revise(self.root, revised, "test owner changed metric", 2)
        self.assertEqual(mission.snapshot(self.root)["metrics"][0]["status"], "NO_DATA")

    def test_stale_concurrent_writer_is_rejected_without_lost_update(self):
        self.init()
        mission.record(self.root, self.observation, 1)
        before = mission.store_path(self.root).read_bytes()
        with self.assertRaises(mission.MissionError):
            mission.learn(self.root, self.lesson, 1)
        self.assertEqual(mission.store_path(self.root).read_bytes(), before)
        self.assertEqual(mission.load(self.root)["revision"], 2)

    def test_atomic_failure_keeps_previous_file_and_releases_lock(self):
        self.init()
        before = mission.store_path(self.root).read_bytes()
        with patch.object(mission.os, "replace", side_effect=OSError("simulated failure")):
            with self.assertRaises(OSError):
                mission.record(self.root, self.observation, 1)
        self.assertEqual(mission.store_path(self.root).read_bytes(), before)
        self.assertFalse(mission.store_path(self.root).with_suffix(".lock").exists())
        self.assertEqual(list(mission.store_path(self.root).parent.glob(".mission-*")), [])

    def test_lock_and_integrity_errors_do_not_reset_memory(self):
        self.init()
        path = mission.store_path(self.root)
        lock = path.with_suffix(".lock")
        lock.write_text("another writer", encoding="utf-8")
        with self.assertRaises(mission.MissionError):
            mission.record(self.root, self.observation, 1)
        self.assertTrue(lock.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        data["definition_history"][0]["definition"]["goal"] = "silent drift"
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(mission.MissionError):
            mission.snapshot(self.root)

    def test_user_expertise_is_recovered_and_not_replaced_by_unadopted_hypothesis(self):
        self.init()
        mission.learn(self.root, self.lesson, 1)
        proposal = dict(self.lesson, id="LESSON-002", kind="HYPOTHESIS", support="AGENT_HYPOTHESIS", status="PROPOSED", supersedes="LESSON-001")
        proposal.pop("decision_source")
        mission.learn(self.root, proposal, 2)
        snapshot = mission.snapshot(self.root)
        self.assertEqual([item["id"] for item in snapshot["adopted_lessons"]], ["LESSON-001"])
        self.assertEqual([item["id"] for item in snapshot["proposed_lessons"]], ["LESSON-002"])
        proposal = dict(proposal, id="LESSON-003", status="ADOPTED", decision_source="agent says yes")
        with self.assertRaises(mission.MissionError):
            mission.learn(self.root, proposal, 3)

    def test_lesson_retirement_preserves_history(self):
        self.init()
        mission.learn(self.root, self.lesson, 1)
        retired = dict(self.lesson, id="LESSON-002", status="RETIRED", supersedes="LESSON-001")
        mission.learn(self.root, retired, 2)
        self.assertEqual(mission.snapshot(self.root)["adopted_lessons"], [])
        self.assertEqual(len(mission.load(self.root)["lessons"]), 2)

    def test_different_users_and_projects_do_not_share_learning(self):
        self.init()
        mission.learn(self.root, self.lesson, 1)
        other = self.root / "other-user-repo"
        (other / ".project-master").mkdir(parents=True)
        mission.initialize(other, self.definition, "another owner")
        self.assertEqual(mission.snapshot(other)["adopted_lessons"], [])
        self.assertEqual(len(mission.snapshot(self.root)["adopted_lessons"]), 1)

    def test_private_memory_and_inputs_are_git_ignored(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True, capture_output=True)
        self.init()
        relative = str(mission.store_path(self.root).relative_to(self.root))
        result = subprocess.run(["git", "-C", str(self.root), "check-ignore", relative], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        input_path = mission.store_path(self.root).parent / "lesson-input.json"
        input_path.write_text(json.dumps(self.lesson), encoding="utf-8")
        result = subprocess.run(["git", "-C", str(self.root), "check-ignore", str(input_path.relative_to(self.root))], capture_output=True, check=False)
        self.assertEqual(result.returncode, 0)

    def test_evidence_outside_project_and_duplicate_records_are_rejected(self):
        self.init()
        self.observation["evidence"] = "../outside.json"
        with self.assertRaises(mission.MissionError):
            mission.record(self.root, self.observation, 1)
        self.observation["evidence"] = "evidence.json"
        mission.record(self.root, self.observation, 1)
        with self.assertRaises(mission.MissionError):
            mission.record(self.root, self.observation, 2)
        self.assertEqual(len(mission.load(self.root)["observations"]), 1)

    def test_nan_future_observations_and_invalid_dates_are_rejected(self):
        self.init()
        self.observation["value"] = float("nan")
        with self.assertRaises(mission.MissionError):
            mission.record(self.root, self.observation, 1)
        self.observation["value"] = 3
        self.observation["observed_at"] = (self.now + timedelta(days=1)).isoformat()
        with self.assertRaises(mission.MissionError):
            mission.record(self.root, self.observation, 1)

    def test_cli_snapshot_is_read_only_and_does_not_touch_legacy_state(self):
        legacy = self.root / ".project-master/STATE.yaml"
        legacy.write_text('{"schema_version":"2.1"}', encoding="utf-8")
        self.init()
        before = mission.store_path(self.root).read_bytes()
        result = subprocess.run([sys.executable, str(SKILL / "scripts/mission.py"), "--root", str(self.root), "show"], capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["goal"], self.definition["goal"])
        self.assertEqual(mission.store_path(self.root).read_bytes(), before)
        self.assertEqual(legacy.read_text(encoding="utf-8"), '{"schema_version":"2.1"}')


if __name__ == "__main__":
    unittest.main()
