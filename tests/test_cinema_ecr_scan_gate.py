"""Negative controls for the immutable DSG Cinema AWS ECR security gate."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_cinema_ecr_scan.py"
WORKFLOW = ROOT / ".github" / "workflows" / "build-aws-cinema.yml"


def response(status="COMPLETE", counts=None):
    return {
        "imageScanStatus": {"status": status},
        "imageScanFindings": {
            "findingSeverityCounts": {} if counts is None else counts,
            "findings": [],
        },
    }


class EcrScanGateTests(unittest.TestCase):
    def run_gate(self, payload):
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            [sys.executable, str(SCRIPT)],
            input=raw,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_zero_finding_complete_scan_passes(self):
        result = self.run_gate(response())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("AWS_CINEMA_ECR_SCAN_GATE=PASS", result.stdout)

    def test_original_ten_high_fails(self):
        result = self.run_gate(
            response(counts={"HIGH": 10, "MEDIUM": 22, "LOW": 11})
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("UNRESOLVED_CRITICAL_OR_HIGH", result.stdout)
        self.assertNotIn("SCAN_GATE=PASS", result.stdout)

    def test_any_critical_fails(self):
        self.assertNotEqual(
            self.run_gate(response(counts={"CRITICAL": 1})).returncode, 0
        )

    def test_medium_only_is_not_an_unapproved_waiver(self):
        # MEDIUM is reported; the separate owner release policy still applies.
        result = self.run_gate(response(counts={"MEDIUM": 4}))
        self.assertEqual(result.returncode, 0)
        self.assertIn("medium=4", result.stdout)

    def test_nonterminal_statuses_fail(self):
        for status in ("FAILED", "IN_PROGRESS", "UNKNOWN", None):
            with self.subTest(status=status):
                self.assertNotEqual(self.run_gate(response(status)).returncode, 0)

    def test_corrupted_and_missing_scan_metadata_fail(self):
        for payload in ("{", [], {}, {"imageScanStatus": {"status": "COMPLETE"}}, {
            "imageScanStatus": {"status": "COMPLETE"},
            "imageScanFindings": {"findingSeverityCounts": None},
        }):
            with self.subTest(payload=payload):
                self.assertNotEqual(self.run_gate(payload).returncode, 0)

    def test_invalid_severity_counts_fail(self):
        for count in ("0", False, None, -1, 0.5, {"value": 0}):
            with self.subTest(count=count):
                self.assertNotEqual(
                    self.run_gate(response(counts={"HIGH": count})).returncode, 0
                )

    def test_workflow_applies_gate_after_real_scan_before_readiness(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/verify_cinema_ecr_scan.py", workflow)
        self.assertIn('printf \'%s\\n\' "$FINDINGS" | python3 scripts/verify_cinema_ecr_scan.py', workflow)
        self.assertLess(
            workflow.index('aws ecr describe-image-scan-findings'),
            workflow.index('printf \'%s\\n\' "$FINDINGS" | python3'),
        )
        self.assertIn("test_cinema_ecr_scan_gate.py", workflow)


if __name__ == "__main__":
    unittest.main()
