#!/usr/bin/env python3
"""Interaction-map behavior tests: edits, data contracts, scoped stops and isolation."""

from __future__ import annotations

import base64
import copy
import json
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree as ET

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))

import workflow  # noqa: E402

EXAMPLE = SKILL / "assets/templates/WORKFLOW-plugin-example.drawio"


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="project-master-workflow-")
        self.root = Path(self.temporary.name)
        self.file = self.root / "workflow.drawio"
        self.file.write_bytes(EXAMPLE.read_bytes())
        self.document = ET.parse(self.file)
        self.contract = workflow.load_contract(self.file)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def cell(self, identity: str) -> ET.Element:
        return self.document.find(f".//*[@id='{identity}']")

    def saved_contract(self):
        self.document.write(self.file, encoding="utf-8", xml_declaration=True)
        return workflow.load_contract(self.file)

    def errors(self, contract=None, root=None):
        return workflow.validate(contract or self.contract, root)[0]

    def cli(self, command: str, *args: str):
        return subprocess.run([sys.executable, str(SKILL / "scripts/workflow.py"), command, str(self.file), *args], capture_output=True, text=True, check=False)

    def test_example_has_valid_data_and_recovery_routes(self):
        self.assertEqual(workflow.validate(self.contract), ([], []))
        self.assertEqual(len(self.contract["nodes"]), 11)
        self.assertEqual(self.cli("validate", "--strict").returncode, 0)

    def test_producer_mismatch_is_rejected(self):
        self.contract["edges"]["E02"]["pm_artifact"] = "unknown.payload"
        self.assertTrue(any("does not produce unknown.payload" in error for error in self.errors()))
        self.assertTrue(any("does not accept unknown.payload" in error for error in self.errors()))

    def test_missing_input_is_rejected(self):
        self.contract["nodes"]["N03"]["pm_inputs"] += ",missing.context"
        self.assertTrue(any("inputs have no producer: missing.context" in error for error in self.errors()))

    def test_dangling_endpoint_is_rejected(self):
        self.contract["edges"]["E05"]["target"] = "deleted-node"
        self.assertTrue(any("endpoints must reference managed nodes" in error for error in self.errors()))

    def test_user_added_arrow_cannot_silently_change_contract(self):
        self.cell("E02").attrib.pop("pm_kind")
        errors = self.errors(self.saved_contract())
        self.assertTrue(any("connected workflow arrow has no pm_kind" in error for error in errors))

    def test_stop_requires_reason_origin_and_resume_condition(self):
        self.contract["nodes"]["N04"].pop("pm_resume_when")
        self.contract["nodes"]["N04"].pop("pm_origin")
        errors = self.errors()
        self.assertTrue(any("gate requires pm_resume_when" in error for error in errors))
        self.assertTrue(any("invalid pm_origin" in error for error in errors))

    def test_stop_cannot_claim_to_block_unrelated_upstream_skill(self):
        self.contract["nodes"]["N04"]["pm_blocks"] = "N02"
        self.assertTrue(any("pm_blocks must be downstream" in error for error in self.errors()))

    def test_hypothesis_is_not_presented_as_verified_constraint(self):
        self.contract["nodes"]["N04"]["pm_origin"] = "HYPOTHESIS"
        errors, warnings = workflow.validate(self.contract)
        self.assertEqual(errors, [])
        self.assertTrue(any("unverified constraint" in warning for warning in warnings))

    def test_even_a_single_bypass_of_authorization_is_rejected(self):
        self.contract["edges"]["BYPASS"] = {
            "id": "BYPASS", "pm_kind": "transition", "source": "N03", "target": "N05",
            "pm_mode": "control", "pm_when": "bypass", "label": "bypass",
        }
        self.contract["edges"]["E03"]["pm_when"] = "normal route"
        self.assertTrue(any("WRITE has a route without an AUTHORIZATION gate" in error for error in self.errors()))

    def test_read_only_external_node_does_not_require_authorization(self):
        self.contract["nodes"]["N05"]["pm_effect"] = "READ"
        self.contract["nodes"]["N04"]["pm_stop_type"] = "INPUT"
        self.assertEqual(self.errors(), [])

    def test_retry_cycle_requires_positive_bound(self):
        self.contract["edges"]["E10"].pop("pm_max_attempts")
        self.assertTrue(any("unbounded cycle" in error for error in self.errors()))
        self.contract["edges"]["E10"]["pm_max_attempts"] = "0"
        self.assertTrue(any("positive integer" in error for error in self.errors()))

    def test_gate_requires_distinct_conditions_and_failure_exit(self):
        self.contract["edges"]["E08"]["pm_when"] = self.contract["edges"]["E04"]["pm_when"]
        self.assertTrue(any("distinct explicit conditions" in error for error in self.errors()))

    def test_layout_style_and_saved_editor_metadata_do_not_change_contract_hash(self):
        before = workflow.fingerprint(self.contract)
        self.document.getroot().set("modified", "2026-10-10T10:00:00Z")
        self.cell("N02").find("mxCell").set("style", "rounded=0;fillColor=#ffffff;")
        self.cell("N02").find("mxCell/mxGeometry").set("x", "999")
        after = self.saved_contract()
        self.assertEqual(workflow.fingerprint(after), before)
        self.assertFalse(workflow.compare(self.contract, after)["contract_changed"])

    def test_contract_edit_detected_by_id_not_geometry(self):
        before = copy.deepcopy(self.contract)
        self.contract["nodes"]["N04"]["pm_resume_when"] = "new permission condition"
        difference = workflow.compare(before, self.contract)
        self.assertTrue(difference["contract_changed"])
        self.assertEqual(difference["nodes"]["changed"], {"N04": ["pm_resume_when"]})

    def test_human_label_change_is_not_ignored_as_layout(self):
        before = copy.deepcopy(self.contract)
        self.contract["nodes"]["N02"]["label"] = "Skip all checks"
        self.assertTrue(workflow.compare(before, self.contract)["contract_changed"])

    def test_normal_editor_compression_round_trip_preserves_contract(self):
        page = self.document.find("diagram")
        model = page.find("mxGraphModel")
        compressor = zlib.compressobj(wbits=-15)
        encoded = quote(ET.tostring(model, encoding="unicode"), safe="~()*!.'-").encode("utf-8")
        payload = compressor.compress(encoded) + compressor.flush()
        page.remove(model)
        page.text = base64.b64encode(payload).decode("ascii")
        self.assertEqual(workflow.canonical(self.saved_contract()), workflow.canonical(self.contract))

    def test_editor_userobject_wrapper_is_supported(self):
        self.cell("N02").tag = "UserObject"
        self.assertEqual(workflow.canonical(self.saved_contract()), workflow.canonical(self.contract))

    def test_multi_page_selection_is_explicit(self):
        page = copy.deepcopy(self.document.find("diagram"))
        page.set("id", "second-page")
        self.document.getroot().append(page)
        self.document.write(self.file, encoding="utf-8")
        with self.assertRaises(workflow.WorkflowError):
            workflow.load_contract(self.file)
        self.assertEqual(workflow.load_contract(self.file, "second-page")["page"], "second-page")

    def test_unreachable_node_and_nonterminating_path_are_rejected(self):
        self.contract["edges"].pop("E11")
        self.assertTrue(any("N11: unreachable" in error for error in self.errors()))
        self.contract["edges"].pop("E07")
        self.contract["edges"].pop("E09")
        self.assertTrue(any("N07: no path to an outcome" in error for error in self.errors()))

    def test_verification_label_alone_is_not_evidence(self):
        self.contract["nodes"]["N02"]["pm_status"] = "VERIFIED"
        errors = self.errors()
        self.assertTrue(any("VERIFIED requires pm_evidence" in error for error in errors))
        self.assertTrue(any("implemented node requires pm_implementation" in error for error in errors))

    def test_references_checked_without_executing_implementation(self):
        (self.root / "impl.py").write_text("raise RuntimeError('must not execute')", encoding="utf-8")
        (self.root / "evidence.md").write_text("# Evidence for human review", encoding="utf-8")
        self.contract["nodes"]["N02"].update({"pm_status": "VERIFIED", "pm_implementation": "impl.py", "pm_evidence": "evidence.md"})
        errors, warnings = workflow.validate(self.contract, self.root)
        self.assertEqual(errors, [])
        self.assertTrue(any("file presence is not proof of success" in warning for warning in warnings))
        self.contract["nodes"]["N02"]["pm_evidence"] = "missing.md"
        self.assertTrue(any("missing reference" in error for error in self.errors(root=self.root)))

    def test_reference_cannot_escape_root_even_through_symlink(self):
        self.contract["nodes"]["N02"]["pm_implementation"] = "../outside.md"
        self.assertTrue(any("escapes project root" in error for error in self.errors(root=self.root)))
        (self.root / "outside-link").symlink_to(SKILL / "SKILL.md")
        self.contract["nodes"]["N02"]["pm_implementation"] = "outside-link"
        self.assertTrue(any("escapes project root" in error for error in self.errors(root=self.root)))

    def test_parser_rejects_duplicates_and_entity_declarations(self):
        self.cell("N02").set("id", "N01")
        with self.assertRaises(workflow.WorkflowError):
            self.saved_contract()
        with self.assertRaises(workflow.WorkflowError):
            workflow.parse_xml(b'<!DOCTYPE x [<!ENTITY a "value">]><mxGraphModel/>')
        with self.assertRaises(workflow.WorkflowError):
            workflow.parse_xml('<!DOCTYPE x [<!ENTITY a "value">]><mxGraphModel/>'.encode("utf-16"))

    def test_compressed_input_has_a_bounded_expansion(self):
        page = ET.Element("diagram")
        compressor = zlib.compressobj(wbits=-15)
        payload = compressor.compress(b"a" * (workflow.MAX_BYTES + 2)) + compressor.flush()
        page.text = base64.b64encode(payload).decode("ascii")
        with self.assertRaises(workflow.WorkflowError):
            workflow.decode_page(page)

    def test_cli_inspect_compare_and_validate_do_not_write_files(self):
        before = {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()}
        output = self.cli("inspect")
        self.assertEqual(output.returncode, 0, output.stderr)
        self.assertEqual(len(json.loads(output.stdout)["nodes"]), 11)
        comparison = self.cli("compare", "--baseline", str(EXAMPLE))
        self.assertEqual(comparison.returncode, 0, comparison.stderr)
        self.assertFalse(json.loads(comparison.stdout)["contract_changed"])
        self.assertEqual(self.cli("validate", "--strict").returncode, 0)
        after = {path.name: path.read_bytes() for path in self.root.iterdir() if path.is_file()}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
