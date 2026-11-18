import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import plan_context


class PlanContextTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.directory = self.root / ".project-master"
        self.directory.mkdir()
        self.config = {"source": "plan.json", "goal": "R2", "current": "R1", "pending": "pending.json"}
        self.plan = {"revision": 1, "steps": [
            {"id": "R1", "title": "Pilot reviewed", "body": "Owner reviews a sample", "done": False},
            {"id": "R2", "title": "Service usable", "body": "A new user completes the workflow", "done": False},
        ]}

    def write(self):
        (self.directory / "plan-context.json").write_text(json.dumps(self.config))
        (self.directory / "plan.json").write_text(json.dumps(self.plan))

    def test_reads_saved_update_and_distinguishes_mark_from_evidence(self):
        evidence = self.directory / "decision.md"
        evidence.write_bytes(b"Sample review recorded")
        self.plan["steps"][0]["links"] = [{
            "path": "decision.md", "label": "Review record",
            "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        }]
        self.write()
        before = plan_context.load(self.root)
        self.assertEqual(before["goal"]["id"], "R2")
        self.assertFalse(before["current"]["checklist_marked"])
        self.assertEqual(before["current"]["links"][0]["status"], "matches_snapshot")
        evidence.write_bytes(b"Edited record")
        self.plan["revision"] += 1
        self.plan["steps"][0]["body"] = "Owner reviews two samples"
        self.write()
        after = plan_context.load(self.root)
        self.assertEqual(after["revision"], 2)
        self.assertEqual(after["current"]["acceptance_criterion"], "Owner reviews two samples")
        self.assertEqual(after["current"]["links"][0]["status"], "changed")

    def test_opt_in_pending_and_escape(self):
        self.assertIsNone(plan_context.load(self.root))
        self.write()
        pending = self.directory / "pending.json"
        pending.touch()
        with self.assertRaisesRegex(ValueError, "update pending"):
            plan_context.load(self.root)
        pending.unlink()
        self.config["source"] = "../outside.json"
        self.write()
        with self.assertRaisesRegex(ValueError, "leaves project memory"):
            plan_context.load(self.root)
